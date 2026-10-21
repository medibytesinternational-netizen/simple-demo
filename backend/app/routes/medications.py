from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import credits, medicines
from ..services.context import build_context
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.identity import require
from ..services.llm import generate_draft
from ..services.rules import evaluate_rules
from ..services.timeline import event_to_dict, get_state, require_open_encounter
from .common import (
    _patient_encounter,
    _state,
)

router = APIRouter()

MIN_TEXT = 10


def _long_enough(value: str, label: str) -> str:
    value = (value or "").strip()
    if len(value) < MIN_TEXT:
        raise ValueError(f"{label} needs at least {MIN_TEXT} characters")
    return value


class ResolveRequest(BaseModel):
    decision: Literal["continue", "hold", "stop", "change"]
    note: str

    @field_validator("note")
    @classmethod
    def note_is_real(cls, value: str) -> str:
        return _long_enough(value, "note")


class OrderRequest(BaseModel):
    action: Literal["start", "stop", "change"]
    drug: str
    dose: str | None = None
    route: str | None = None
    frequency: str | None = None
    indication: str | None = None
    reason: str

    @field_validator("drug")
    @classmethod
    def drug_named(cls, value: str) -> str:
        value = (value or "").strip()
        if len(value) < 2:
            raise ValueError("drug is required")
        return value

    @field_validator("reason")
    @classmethod
    def reason_is_real(cls, value: str) -> str:
        return _long_enough(value, "reason")


class AdministrationRequest(BaseModel):
    status: Literal["given", "held", "refused"]
    given_at: str | None = None
    note: str | None = None


@router.get("/medications")
def medications(encounter_id: str | None = None, db: Session = Depends(get_db)):
    _, _, state = _state(db, encounter_id)
    return {
        "home_medications": state["home_meds"],
        "current_medications": state["active_meds"],
    }


@router.get("/medications/reconciliation")
def medication_reconciliation(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db, encounter_id)
    return medicines.reconciliation_with_decisions(db, patient, encounter, state)


@router.post("/medications/reconciliation/generate", dependencies=[Depends(require("reconcile"))])
def generate_reconciliation(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    credits.charge(db, "medicine_reconciliation", feature="F6")
    recon = medicines.reconciliation_with_decisions(db, patient, encounter, state)
    context = build_context(db, patient, encounter, state, "F6", extra={"reconciliation": recon})
    content, llm_call = generate_draft(db, "F6", context)
    draft = create_draft(db, feature="F6", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "reconciliation": recon, "llm": {"mode": llm_call.mode}}


@router.post(
    "/medications/reconciliation/{discrepancy_id}/resolve",
    dependencies=[Depends(require("resolve_discrepancy"))],
)
def resolve_discrepancy(discrepancy_id: str, body: ResolveRequest, db: Session = Depends(get_db)):
    """Record what a clinician decided. This never creates or changes an order."""
    patient, encounter, state = _state(db)
    try:
        result = medicines.record_decision(
            db, patient, encounter, state, discrepancy_id, body.decision, body.note
        )
    except LookupError:
        raise HTTPException(404, "Discrepancy not found")
    db.commit()
    row, item = result["decision"], result["discrepancy"]
    fresh = medicines.reconciliation_with_decisions(db, patient, encounter, get_state(db, patient, encounter))
    return {
        "discrepancy_id": discrepancy_id,
        "decision": row.decision,
        "note": row.note,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at.isoformat(),
        "event": event_to_dict(result["event"]),
        "proposed_order_change": medicines.proposed_order_change(item, row.decision, row.note),
        "unresolved_count": fresh["unresolved_count"],
    }


@router.post("/medications/orders", dependencies=[Depends(require("order_medicine"))])
def order_medicine(body: OrderRequest, db: Session = Depends(get_db)):
    """A doctor starts, stops or changes an inpatient medicine. Ordering is not giving."""
    patient, encounter = _patient_encounter(db)
    require_open_encounter(encounter)
    event = medicines.place_order(
        db,
        patient,
        encounter,
        action=body.action,
        drug=body.drug,
        reason=body.reason,
        fields={
            "dose": body.dose,
            "route": body.route,
            "frequency": body.frequency,
            "indication": body.indication,
        },
    )
    state = get_state(db, patient, encounter)
    alerts = evaluate_rules(db, patient, encounter, state)
    db.commit()
    return {
        "event": event_to_dict(event),
        "new_alerts": [
            {
                "id": alert.id,
                "rule_id": alert.rule_id,
                "severity": alert.severity,
                "title": alert.title,
                "explanation": alert.explanation,
                "evidence_event_ids": alert.evidence_event_ids or [],
            }
            for alert in alerts
        ],
    }


@router.post(
    "/medications/orders/{event_id}/administrations",
    dependencies=[Depends(require("give_medicine"))],
)
def give_medicine(event_id: str, body: AdministrationRequest, db: Session = Depends(get_db)):
    """A nurse records a dose as given, held or refused against the current active order."""
    try:
        event = medicines.record_administration(
            db, event_id, status=body.status, given_at=body.given_at, note=body.note
        )
    except LookupError:
        raise HTTPException(404, "Medicine order not found")
    db.commit()
    return {"event": event_to_dict(event), "administration": event.payload}


@router.get("/medications/administrations")
def administrations(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter = _patient_encounter(db, encounter_id)
    rows = medicines.list_administrations(db, patient, encounter.id)
    return {"administrations": rows, "count": len(rows)}
