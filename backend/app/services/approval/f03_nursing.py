from __future__ import annotations

from typing import Any

from ..timeline import add_audit, add_event
from . import ApprovalContext, after_event


@after_event("F3")
def write_nursing_chart(ctx: ApprovalContext, event: Any) -> None:
    nursing_entries = ctx.payload.get("nursing_entries", [])
    if not nursing_entries:
        return
    nursing_event = add_event(
        ctx.db,
        patient_id=ctx.patient.id,
        encounter_id=ctx.encounter.id,
        type="nursing_chart",
        subtype="f3",
        title="Nursing chart — round instructions",
        body_text="\n".join(str(entry.get("text", "")) for entry in nursing_entries if isinstance(entry, dict)),
        payload={"round_event_id": event.id, "entries": nursing_entries},
        source="F3",
        author_type="model",
        author_name=ctx.approver,
        status="approved",
        approved_by=ctx.approver,
    )
    add_audit(
        ctx.db,
        "nursing_chart_committed",
        "timeline_event",
        nursing_event.id,
        ctx.patient.id,
        after={"round_event_id": event.id, "entries": len(nursing_entries)},
    )
