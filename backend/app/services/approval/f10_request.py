from __future__ import annotations

from typing import Any

from ...db import utcnow
from ...models import InvestigationRequest
from ..timeline import new_id
from . import ApprovalContext, payload_builder


@payload_builder("F10")
def create_investigation_request(ctx: ApprovalContext, event_payload: dict[str, Any]) -> None:
    payload, patient, encounter, draft = ctx.payload, ctx.patient, ctx.encounter, ctx.draft
    indication = payload.get("indication") or {}
    request = InvestigationRequest(
        id=new_id("inv"),
        patient_id=patient.id,
        encounter_id=encounter.id,
        request_type=payload.get("request_type", "laboratory"),
        study=payload.get("study", "Investigation"),
        indication=indication.get("text", "") if isinstance(indication, dict) else str(indication),
        diagnosis=payload.get("diagnosis", ""),
        allergies_to_verify=payload.get("allergies_to_verify", []),
        priority=payload.get("priority", "routine"),
        instructions=payload.get("instructions", ""),
        status="approved",
        draft_id=draft.id,
        approved_by=ctx.approver,
        created_at=utcnow(),
    )
    ctx.db.add(request)
    ctx.db.flush()
    event_payload["request_id"] = request.id
