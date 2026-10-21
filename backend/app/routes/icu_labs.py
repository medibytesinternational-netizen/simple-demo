from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..services.identity import require
from ..services.identity import acting_name
from ..db import get_db, utcnow
from ..models import (
    Alert,
    Encounter,
)
from ..services.context import build_context
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.llm import generate_draft
from ..services.timeline import (
    add_audit,
    event_to_dict,
    get_event,
)
from .common import (
    _state,
)

router = APIRouter()


# --------------------------------------------------------------------------
# ICU flow sheets (F7) and investigations support
# --------------------------------------------------------------------------
def _icu_encounter_id(db: Session, encounter_id: str | None) -> str | None:
    if encounter_id and db.get(Encounter, encounter_id):
        return encounter_id
    icu = db.get(Encounter, "enc_icu_1")
    return icu.id if icu else None


@router.get("/icu/flow-sheet")
def icu_flow_sheet(encounter_id: str | None = None, db: Session = Depends(get_db)):
    resolved = _icu_encounter_id(db, encounter_id)
    _, _, state = _state(db, resolved)
    return {
        "encounter": state["encounter"],
        "shift_window": state.get("icu_shift_window", {}),
        "entries": state.get("icu_entries", []),
    }


@router.post("/icu/flow-sheet/generate", dependencies=[Depends(require("clinical_draft"))])
def generate_icu_flow_sheet(encounter_id: str | None = None, db: Session = Depends(get_db)):
    resolved = _icu_encounter_id(db, encounter_id)
    patient, encounter, state = _state(db, resolved)
    context = build_context(db, patient, encounter, state, "F7")
    content, llm_call = generate_draft(db, "F7", context)
    draft = create_draft(db, feature="F7", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode, "latency_ms": llm_call.latency_ms}}


@router.get("/investigations")
def investigations(encounter_id: str | None = None, db: Session = Depends(get_db)):
    _, _, state = _state(db, encounter_id)
    return {
        "labs": state["latest_labs"],
        "unreviewed": state["unreviewed_labs"],
        "reviewed_count": len(state["latest_labs"]) - len(state["unreviewed_labs"]),
    }


@router.post("/labs/{event_id}/review", dependencies=[Depends(require("review_lab"))])
def review_lab(event_id: str, db: Session = Depends(get_db)):
    event = get_event(db, event_id)
    if event.type != "lab_result":
        raise HTTPException(400, "Event is not a laboratory result")
    before = dict(event.payload or {})
    event.payload = {**before, "review_status": "reviewed"}
    flag_modified(event, "payload")
    add_audit(
        db,
        "lab_reviewed",
        "timeline_event",
        event.id,
        event.patient_id,
        before=before,
        after=event.payload,
    )
    alerts = list(
        db.scalars(
            select(Alert).where(
                Alert.status == "open",
                Alert.rule_id == "R3",
                Alert.patient_id == event.patient_id,
            )
        )
    )
    for alert in alerts:
        if event.id in (alert.evidence_event_ids or []):
            alert.status = "acknowledged"
            alert.acknowledged_by = acting_name()
            alert.resolved_at = utcnow()
            add_audit(
                db,
                "alert_acknowledged",
                "alert",
                alert.id,
                event.patient_id,
                after={"reason": "Result reviewed", "lab_event_id": event.id},
            )
    db.commit()
    return {"event": event_to_dict(event)}
