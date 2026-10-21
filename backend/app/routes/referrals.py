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
from ..services.context import build_context
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.llm import generate_draft
from ..services.timeline import (
    add_audit,
    add_event,
)
from .common import (
    ReferralCompleteRequest,
    ReferralGenerateRequest,
    TaskActionRequest,
    _referral_dict,
    _state,
)

router = APIRouter()


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
def generate_referral(body: ReferralGenerateRequest | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    context = build_context(db, patient, encounter, state, "F11")
    content, llm_call = generate_draft(db, "F11", context)
    if body and body.specialty:
        content["specialty"] = body.specialty
    if body and body.urgency:
        content["urgency"] = body.urgency
    draft = create_draft(db, feature="F11", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode, "latency_ms": llm_call.latency_ms}}


@router.post("/referrals/{referral_id}/acknowledge", dependencies=[Depends(require("send_request"))])
def acknowledge_referral(referral_id: str, body: TaskActionRequest, db: Session = Depends(get_db)):
    referral = db.get(Referral, referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")
    if referral.status != "sent":
        raise HTTPException(400, f"Referral is {referral.status}; only a sent referral can be acknowledged")
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
    if referral.status not in {"sent", "acknowledged"}:
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
