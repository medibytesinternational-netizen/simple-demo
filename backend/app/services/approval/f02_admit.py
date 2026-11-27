"""F2: signing the admission note admits the patient.

The note is dated and signed now (On / Under). If the patient is on an OPD visit, that visit is
closed and an inpatient visit is opened on the ward named in the note (the bed is chosen later).
A patient who is already an inpatient is not admitted twice.
"""

from __future__ import annotations

from typing import Any

from ...db import utcnow
from ...models import Encounter
from ..admission import admission_header
from ..timeline import add_audit, add_event, new_id
from . import ApprovalContext, after_commit, payload_builder


def _text(value: Any) -> str:
    return str(value.get("text") or "").strip() if isinstance(value, dict) else ""


@payload_builder("F2")
def stamp_admission_header(ctx: ApprovalContext, event_payload: dict[str, Any]) -> None:
    if ctx.payload.get("format") != "admit_v2":
        return
    header = admission_header(ctx.patient, ctx.encounter, ctx.approver, utcnow().strftime("%d %b %Y, %H:%M"))
    event_payload["header"] = header
    ctx.payload["header"] = header


@after_commit("F2")
def admit_patient(ctx: ApprovalContext, event) -> None:
    if ctx.payload.get("format") != "admit_v2":
        return
    current = ctx.encounter
    if (current.kind or "").upper() != "OPD" or current.status != "active":
        return
    now = utcnow()
    ward = _text(ctx.payload.get("ward")) or "Ward to be assigned"
    current.status = "closed"
    current.discharged_at = now
    admitted = Encounter(
        id=new_id("enc"),
        patient_id=ctx.patient.id,
        kind="IPD",
        ward=ward[:80],
        bed=None,
        attending=ctx.approver,
        admitted_at=now,
        status="active",
    )
    ctx.db.add(admitted)
    ctx.db.flush()
    add_event(
        ctx.db,
        patient_id=ctx.patient.id,
        encounter_id=admitted.id,
        type="admission",
        title=f"Admitted to {ward}",
        body_text=f"Admitted under {ctx.approver}. OPD visit closed.",
        payload={"ward": ward, "from_encounter_id": current.id, "admission_note_event_id": event.id,
                 "admission_type": _text(ctx.payload.get("admission_type"))},
        source="admission",
        approved_by=ctx.approver,
    )
    add_audit(
        ctx.db, "patient_admitted", "encounter", admitted.id, ctx.patient.id,
        after={"ward": ward, "from_encounter_id": current.id, "note_event_id": event.id},
    )
