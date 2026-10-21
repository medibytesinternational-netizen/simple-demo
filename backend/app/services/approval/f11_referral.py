from __future__ import annotations

from typing import Any

from ...db import utcnow
from ...models import Referral
from ..timeline import new_id
from . import ApprovalContext, payload_builder


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
        status="sent",
        draft_id=draft.id,
        approved_by=ctx.approver,
        sent_at=utcnow(),
        created_at=utcnow(),
    )
    ctx.db.add(referral)
    ctx.db.flush()
    event_payload["referral_id"] = referral.id
