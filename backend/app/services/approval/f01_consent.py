from __future__ import annotations

from sqlalchemy import select

from ...models import TimelineEvent
from . import ApprovalContext, validator


@validator("F1")
def require_consent(ctx: ApprovalContext) -> None:
    draft = ctx.draft
    consent_events = ctx.db.scalars(
        select(TimelineEvent).where(
            TimelineEvent.patient_id == draft.patient_id,
            TimelineEvent.encounter_id == draft.encounter_id,
            TimelineEvent.type == "consent",
            TimelineEvent.status == "approved",
        )
    ).all()
    granted = any((event.payload or {}).get("granted") is True for event in consent_events)
    if not granted:
        raise ValueError(
            "F1 cannot be approved: record the patient's consent for consultation "
            "capture before signing the note."
        )
