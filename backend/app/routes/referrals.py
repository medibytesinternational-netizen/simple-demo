from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..services.identity import require
from ..services.identity import acting_name
from ..db import get_db, utcnow
from ..models import (
    Referral,
)
from typing import Literal

from pydantic import BaseModel

from ..services.cached.f11_referral import apply_request, infer_specialty
from ..services.context import build_context
from ..services.drafts import (
    approve_draft,
    create_draft,
    draft_to_dict,
    update_draft,
)
from ..services.llm import generate_draft
from ..services import referral_form
from ..services.timeline import add_audit, add_event
from .common import (
    ReferralCompleteRequest,
    TaskActionRequest,
    _referral_dict,
    _state,
)

router = APIRouter()


class ReferralGenerateBody(BaseModel):
    specialty: str | None = None
    urgency: Literal["routine", "urgent", "emergency"] | None = None
    question: str | None = None


@router.get("/referrals")
def referrals(encounter_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Referral).order_by(Referral.created_at.desc())
    if encounter_id:
        stmt = stmt.where(Referral.encounter_id == encounter_id)
    else:
        _, current, _ = _state(db)
        stmt = stmt.where(Referral.encounter_id == current.id)
    rows = list(db.scalars(stmt))
    return {"referrals": [_referral_dict(referral) for referral in rows]}


@router.post("/referrals/generate", dependencies=[Depends(require("clinical_draft"))])
def generate_referral(body: ReferralGenerateBody | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    context = build_context(db, patient, encounter, state, "F11")
    request = {
        "specialty": ((body.specialty or "").strip() if body else "") or infer_specialty(context),
        "urgency": body.urgency if body else None,
        "question": ((body.question or "").strip() if body else ""),
    }
    if not request["specialty"]:
        raise HTTPException(422, "Choose a specialty")
    context["referral_request"] = request
    content, llm_call = generate_draft(db, "F11", context)
    content = apply_request(content, request)
    draft = create_draft(db, feature="F11", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode, "latency_ms": llm_call.latency_ms}}


@router.post("/referrals/{referral_id}/acknowledge", dependencies=[Depends(require("send_request"))])
def acknowledge_referral(referral_id: str, body: TaskActionRequest, db: Session = Depends(get_db)):
    referral = db.get(Referral, referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")
    if referral.status not in {"queued", "sent"}:
        raise HTTPException(400, f"Referral is {referral.status}; only a queued or sent referral can be acknowledged")
    referral.status = "acknowledged"
    referral.acknowledged_at = utcnow()
    update_event = add_event(
        db,
        patient_id=referral.patient_id,
        encounter_id=referral.encounter_id,
        type="referral_update",
        subtype=referral.specialty,
        title=f"Referral acknowledged — {referral.specialty}",
        body_text="The specialist service acknowledged the referral. No external transmission occurred in this demo.",
        payload={"referral_id": referral.id, "status": "acknowledged"},
        source="referral",
        author_type="human",
        author_name=acting_name(),
    )
    add_audit(
        db,
        "referral_acknowledged",
        "referral",
        referral.id,
        referral.patient_id,
        actor_name=acting_name(),
        after={"status": referral.status, "specialty": referral.specialty},
    )
    db.commit()
    return _referral_dict(referral)


@router.post("/referrals/{referral_id}/complete", dependencies=[Depends(require("send_request"))])
def complete_referral(referral_id: str, body: ReferralCompleteRequest, db: Session = Depends(get_db)):
    referral = db.get(Referral, referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")
    if referral.status not in {"queued", "sent", "acknowledged"}:
        raise HTTPException(400, f"Referral is {referral.status}; it cannot be completed")
    referral.status = "completed"
    referral.completed_at = utcnow()
    referral.response_summary = body.response_summary.strip()
    consult = add_event(
        db,
        patient_id=referral.patient_id,
        encounter_id=referral.encounter_id,
        type="referral_consult",
        subtype=referral.specialty,
        title=f"Specialist response — {referral.specialty}",
        body_text=referral.response_summary or "Referral marked complete without a written response.",
        payload={
            "referral_id": referral.id,
            "status": "completed",
            "response_summary": referral.response_summary,
        },
        source="referral",
        author_type="human",
        author_name=acting_name(),
    )
    referral.consult_event_id = consult.id
    add_audit(
        db,
        "referral_completed",
        "referral",
        referral.id,
        referral.patient_id,
        actor_name=acting_name(),
        after={"status": referral.status, "response_summary": referral.response_summary},
    )
    db.commit()
    return _referral_dict(referral)


# --------------------------------------------------------------------------
# Referral form, part one: dictated fields are populated only from the six-section API note.
# --------------------------------------------------------------------------
from ..models import Draft  # noqa: E402


class ReferralFormBody(BaseModel):
    content: dict


def _latest_form(db: Session, patient_id: str) -> Draft | None:
    drafts = db.scalars(
        select(Draft).where(Draft.feature == "F11", Draft.patient_id == patient_id).order_by(Draft.created_at.desc())
    ).all()
    return next((d for d in drafts if (d.content or {}).get("format") == referral_form.REFERRAL_FORMAT), None)


@router.get("/referrals/form", dependencies=[Depends(require("refer"))])
def latest_referral_form(db: Session = Depends(get_db)):
    patient, _, _ = _state(db)
    draft = _latest_form(db, patient.id)
    return {"draft": draft_to_dict(draft) if draft else None}


def _open_form(db: Session, draft_id: str) -> Draft:
    patient, _, _ = _state(db)
    draft = db.get(Draft, draft_id)
    if not draft or draft.patient_id != patient.id or (draft.content or {}).get("format") != referral_form.REFERRAL_FORMAT:
        raise HTTPException(404, "Referral form not found")
    return draft


@router.patch("/referrals/form/{draft_id}", dependencies=[Depends(require("refer"))])
def edit_referral_form(draft_id: str, body: ReferralFormBody, db: Session = Depends(get_db)):
    draft = _open_form(db, draft_id)
    content = {**(draft.content or {}), **body.content, "format": referral_form.REFERRAL_FORMAT,
               "header": (draft.content or {}).get("header") or {}}
    content["urgency"] = referral_form.URGENCY.get(content.get("referral_type") or "", "routine")
    content["specialty"] = str((content.get("department") or {}).get("text") or "")
    content["specialist"] = str((content.get("unit_chief") or {}).get("text") or "")
    content["not_documented"] = referral_form.missing(content)
    try:
        update_draft(db, draft, content)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return {"draft": draft_to_dict(draft)}


@router.post("/referrals/form/{draft_id}/approve", dependencies=[Depends(require("refer"))])
def approve_referral_form(draft_id: str, db: Session = Depends(get_db)):
    draft = _open_form(db, draft_id)
    try:
        event = approve_draft(db, draft, None)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return {"draft": draft_to_dict(draft), "event_id": event.id, "document_id": event.document_id}


@router.post("/referrals/form/{draft_id}/discard", dependencies=[Depends(require("refer"))])
def discard_referral_form(draft_id: str, db: Session = Depends(get_db)):
    from ..services.drafts import reject_draft

    draft = _open_form(db, draft_id)
    try:
        reject_draft(db, draft, "Discarded by the referring doctor")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return {"draft": draft_to_dict(draft)}
