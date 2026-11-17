"""Daily progress notes (doctor's and nurse's) for the open patient.

POST /progress-notes/record              dictation -> MediBytes pipeline (role: doctor | nurse)
GET  /progress-notes/record/{audio_id}   poll; when written, the entry is signed by who recorded it
GET  /progress-notes                     one table (doctors and nurses), oldest first
POST /progress-notes/report              the table as a stored, printable report on the timeline
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db, utcnow
from ..models import Draft, TimelineEvent
from ..services import credits, pipeline
from ..services import progress
from ..services.context import create_transcript_event
from ..services.drafts import approve_draft, create_draft
from ..services.identity import acting_name
from ..services.note_document import GENERATED_KIND
from ..services.ocr import new_document
from ..services.timeline import add_audit, add_event, require_open_encounter
from .common import _state
from .notes import MAX_AUDIO_BYTES, _looks_like_audio

router = APIRouter()


def _role(role: str | None) -> str:
    role = role or progress.default_role()
    if role not in progress.ROLES:
        raise HTTPException(422, "Role must be doctor or nurse")
    if not progress.may_write(role):
        raise HTTPException(403, f"You cannot write the {progress.TABLE_TITLE[role].lower()}")
    return role


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


@router.post("/progress-notes/record")
async def record_progress(file: UploadFile = File(...), role: str = Form(""), db: Session = Depends(get_db)):
    role = _role(role)
    patient, encounter, _ = _state(db)
    require_open_encounter(encounter)
    if not _looks_like_audio(file.filename, file.content_type):
        raise HTTPException(415, "That file is not audio. Upload mp3, wav, m4a, webm or ogg.")
    contents = await file.read(MAX_AUDIO_BYTES + 1)
    if len(contents) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio too large (max 64 MB)")
    if not contents:
        raise HTTPException(400, "The audio file is empty")
    if not pipeline.configured():
        raise HTTPException(400, "Voice notes need the MediBytes pipeline; set OPENAI_API_KEY")
    credits.charge(db, "voice_note", feature="F4", mode="live")
    audio_id = str(uuid.uuid4())
    receipt = pipeline.submit(
        contents, file.filename or "progress.webm", file.content_type or "audio/webm", audio_id, "F4",
        extra={"role": role},
    )
    add_audit(db, "progress_note_submitted", "patient", patient.id, patient.id,
              after={"audio_id": audio_id, "role": role, "encounter_id": encounter.id})
    db.commit()
    return {"audio_id": audio_id, "role": role, "status": receipt.get("status", "running")}


@router.get("/progress-notes/record/{audio_id}")
def progress_status(audio_id: str, db: Session = Depends(get_db)):
    patient, encounter, _ = _state(db)
    for event in db.scalars(
        select(TimelineEvent).where(
            TimelineEvent.patient_id == patient.id, TimelineEvent.type == "transcript", TimelineEvent.subtype == "F4"
        )
    ).all():
        if (event.payload or {}).get("audio_id") == audio_id:
            drafts = db.scalars(select(Draft).where(Draft.feature == "F4", Draft.patient_id == patient.id)).all()
            match = next((d for d in drafts if event.id in (d.created_from_event_ids or [])), None)
            if match and match.committed_event_id:
                return {"status": "succeeded", "entry": _row(db.get(TimelineEvent, match.committed_event_id))}
    if not pipeline.configured():
        raise HTTPException(400, "Voice notes need the MediBytes pipeline; set OPENAI_API_KEY")
    result = pipeline.fetch(audio_id)
    if result is None:
        raise HTTPException(404, "No recording with that id")
    job_status = result.get("job_status")
    if job_status == "failed":
        return {"status": "failed", "error": result.get("job_error") or "The recording could not be processed"}
    if job_status != "succeeded":
        return {"status": job_status or "running"}
    require_open_encounter(encounter)
    note = result.get("note") or {}
    text = str(result.get("transcript") or "").strip()
    if not text or not pipeline.has_items(note):
        return {"status": "failed", "error": "No speech was detected in the recording"}
    role = _role(result.get("role"))
    event = create_transcript_event(db, patient, encounter, "F4", text, f"{progress.TITLE[role]} dictation")
    event.payload = {**(event.payload or {}), "audio_id": audio_id, "pipeline_note": note}
    content = pipeline.draft_content("F4", note, event.id, event.payload.get("segments") or [])
    draft = create_draft(db, feature="F4", patient=patient, encounter=encounter,
                         content={**content, "role": role}, created_from_event_ids=[event.id])
    try:
        signed = approve_draft(db, draft, None)
    except ValueError as exc:
        db.rollback()
        return {"status": "failed", "error": str(exc)}
    db.commit()
    return {"status": "succeeded", "entry": _row(signed)}


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
