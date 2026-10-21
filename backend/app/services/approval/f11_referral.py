from __future__ import annotations

from typing import Any

from ...db import utcnow
from ...models import Referral
from ..timeline import new_id
from ..cached.f11_referral import PLACEHOLDER_QUESTION
from . import ApprovalContext, payload_builder, validator


@validator("F11")
def refuse_placeholder_question(ctx: ApprovalContext) -> None:
    question = ctx.payload.get("question") or {}
    text = question.get("text", "") if isinstance(question, dict) else str(question)
    if not text.strip() or " ".join(text.split()).casefold() == PLACEHOLDER_QUESTION.casefold():
        raise ValueError("Write the referral question before approving; it is still the placeholder.")


@payload_builder("F11")
def create_referral(ctx: ApprovalContext, event_payload: dict[str, Any]) -> None:
    payload, patient, encounter, draft = ctx.payload, ctx.patient, ctx.encounter, ctx.draft
    question = payload.get("question") or {}
    history = payload.get("history") or {}
    referral = Referral(
        id=new_id("ref"),
        patient_id=patient.id,
        encounter_id=encounter.id,
        specialty=payload.get("specialty", "Specialist service"),
        specialist=payload.get("specialist", ""),
        question=question.get("text", "") if isinstance(question, dict) else str(question),
        history=history.get("text", "") if isinstance(history, dict) else str(history),
        urgency=payload.get("urgency", "routine"),
        status="queued",
        draft_id=draft.id,
        approved_by=ctx.approver,
        created_at=utcnow(),
    )
    ctx.db.add(referral)
    ctx.db.flush()
    event_payload["referral_id"] = referral.id
