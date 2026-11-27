"""Re-scan signed doctor progress notes and raise any investigation requests they ask for.

Safe to run more than once: open requests for the same study are reused, never duplicated.
Usage: python -m app.scripts.rescan_progress_orders
"""
from __future__ import annotations

from sqlalchemy import select

from ..db import SessionLocal, init_db
from ..models import Encounter, Patient, TimelineEvent
from ..services.approval.f04_progress import raise_requests_for_note


def rescan(db) -> int:
    raised = 0
    events = db.scalars(select(TimelineEvent).where(
        TimelineEvent.type == "progress_note", TimelineEvent.status == "approved")).all()
    for event in events:
        payload = event.payload or {}
        if payload.get("format") != "progress_v2" or payload.get("role", "doctor") != "doctor":
            continue
        patient = db.get(Patient, event.patient_id)
        encounter = db.get(Encounter, event.encounter_id) if event.encounter_id else None
        if not patient or not encounter:
            continue
        approver = (payload.get("signed_by") or {}).get("name") or event.approved_by or "system"
        raised += len(raise_requests_for_note(db, event, patient, encounter, approver))
    db.commit()
    return raised


if __name__ == "__main__":
    init_db()
    with SessionLocal() as session:
        print(f"Orders linked from progress notes: {rescan(session)}")
