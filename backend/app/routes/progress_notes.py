"""Daily progress notes (doctor's and nurse's) for the open patient.

GET  /progress-notes                     one table (doctors and nurses), oldest first
POST /progress-notes/report              the table as a stored, printable report on the timeline

Voice dictation uses the shared /notes/transcribe MediBytes API flow and creates a reviewable draft.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db, utcnow
from ..models import TimelineEvent
from ..services import progress
from ..services.identity import acting_name
from ..services.note_document import GENERATED_KIND
from ..services.ocr import new_document
from ..services.timeline import add_audit, add_event
from .common import _state

router = APIRouter()


def _row(event: TimelineEvent) -> dict:
    payload = event.payload or {}
    return {
        "event_id": event.id,
        "role": payload.get("role"),
        "time": event.occurred_at.isoformat() if event.occurred_at else "",
        "notes": progress.notes_text(payload),
        "signed_by": (payload.get("signed_by") or {}).get("name") or event.approved_by or "",
        "orders": [
            {"study": o.get("study"), "request_type": o.get("request_type"), "sentence_index": o.get("sentence_index"),
             "request_id": o.get("request_id"), "priority": o.get("priority")}
            for o in payload.get("orders") or []
        ],
    }


@router.get("/progress-notes")
def progress_tables(db: Session = Depends(get_db)):
    patient, encounter, _ = _state(db)
    # One table: doctors' and nurses' entries together, oldest first, each with who signed it.
    return {"entries": progress.rows(db, patient.id), "can_write": [r for r in progress.ROLES if progress.may_write(r)]}


@router.post("/progress-notes/report")
def progress_report(role: str | None = None, db: Session = Depends(get_db)):
    if role is not None and role not in progress.ROLES:
        raise HTTPException(422, "Role must be doctor or nurse")
    patient, encounter, _ = _state(db)
    table = progress.rows(db, patient.id, role)
    if not table:
        raise HTTPException(400, f"There are no {progress.TABLE_TITLE[role].lower()} yet")
    made_at = utcnow()
    html = progress.render_report_html(progress.header(patient, encounter), role, table, acting_name(), made_at)
    folder = settings.uploads_dir / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    title = progress.TABLE_TITLE[role]
    event = add_event(
        db, patient_id=patient.id, encounter_id=encounter.id, type=progress.REPORT_TYPE, subtype=role or "all",
        title=f"{title} report", body_text=f"{len(table)} entries",
        payload={"role": role or "all", "entries": len(table), "event_ids": [r["event_id"] for r in table]},
        source="F4", author_type="human", author_name=acting_name(), status="approved",
        occurred_at=made_at, approved_by=acting_name(),
    )
    path = folder / f"{event.id}.html"
    path.write_text(html, encoding="utf-8")
    document = new_document(
        db, patient_id=patient.id, encounter_id=encounter.id,
        filename=f"{title} {patient.mrn} {made_at:%Y-%m-%d %H%M}.html", path=str(path), mime="text/html",
        image_kind=GENERATED_KIND, doc_type=progress.REPORT_TYPE,
    )
    document.ocr_status = "confirmed"
    document.confirmed_by = acting_name()
    document.confirmed_at = made_at
    event.document_id = document.id
    add_audit(db, "note_document_stored", "document", document.id, patient.id,
              after={"event_id": event.id, "doc_type": progress.REPORT_TYPE})
    db.commit()
    return {"event_id": event.id, "document_id": document.id, "entries": len(table)}
