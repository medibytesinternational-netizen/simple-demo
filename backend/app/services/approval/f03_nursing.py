from __future__ import annotations

from typing import Any

from ...models import TimelineEvent
from ..timeline import add_audit, add_event
from . import ApprovalContext, after_event

_NURSE = {"nurse", "nursing"}


def _nurse_segment_ids(ctx: ApprovalContext) -> set[str]:
    """Segments of the round transcript that the nurse spoke."""
    ids: set[str] = set()
    for event_id in ctx.draft.created_from_event_ids or []:
        source = ctx.db.get(TimelineEvent, event_id)
        if not source or source.type != "transcript":
            continue
        for segment in (source.payload or {}).get("segments", []):
            if str(segment.get("speaker", "")).strip().lower() in _NURSE:
                ids.add(str(segment.get("segment_id", "")))
    return ids


@after_event("F3")
def write_nursing_chart(ctx: ApprovalContext, event: Any) -> None:
    nursing_entries = ctx.payload.get("nursing_entries", [])
    if not nursing_entries:
        return
    nurse_ids = _nurse_segment_ids(ctx)
    entries = []
    for entry in nursing_entries:
        if not isinstance(entry, dict):
            continue
        # Said, not done: every chart entry is an instruction, never an administration or a result.
        marked = {**entry, "kind": "instruction"}
        if nurse_ids.intersection(str(item) for item in entry.get("source_segment_ids", [])):
            marked["said_by"] = "nurse"
        entries.append(marked)
    nursing_event = add_event(
        ctx.db,
        patient_id=ctx.patient.id,
        encounter_id=ctx.encounter.id,
        type="nursing_chart",
        subtype="f3",
        title="Nursing chart — round instructions",
        body_text="\n".join(str(entry.get("text", "")) for entry in entries),
        payload={"round_event_id": event.id, "entries": entries},
        source="F3",
        author_type="model",
        # The model wrote the entries; the clinician who signed is approved_by (same contract as notes).
        author_name=f"{ctx.draft.model} ({ctx.draft.prompt_version})",
        status="approved",
        approved_by=ctx.approver,
    )
    add_audit(
        ctx.db,
        "nursing_chart_committed",
        "timeline_event",
        nursing_event.id,
        ctx.patient.id,
        after={"round_event_id": event.id, "entries": len(entries)},
    )
