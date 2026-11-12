from __future__ import annotations

import uuid


from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import (
    Draft,
    TimelineEvent,
)
from ..services import credits, pipeline
from ..services.identity import require
from ..services.context import build_context, create_transcript_event
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.llm import DraftGenerationError, fallback_reason, generate_draft
from ..services.timeline import (
    add_audit,
    require_open_encounter,
)
from .common import (
    NoteGenerateRequest,
    _state,
)

router = APIRouter()

MAX_AUDIO_BYTES = 64 * 1024 * 1024
# Formats the transcription service accepts.
AUDIO_EXTENSIONS = {"mp3", "wav", "m4a", "webm", "ogg", "oga", "mp4", "mpeg", "mpga", "flac", "aac"}


def _looks_like_audio(filename: str | None, content_type: str | None) -> bool:
    """Judge by the declared type and the file name only (no byte sniffing).

    A file name with an extension outside the audio set is refused even if it claims audio/*.
    Browsers type picked files unevenly (video/webm, application/octet-stream), so the extension
    decides when it is present; without an extension the declared type must be audio/*.
    """
    declared = (content_type or "").split(";")[0].strip().lower()
    name = (filename or "").rsplit("/", 1)[-1]
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension:
        return extension in AUDIO_EXTENSIONS
    return declared.startswith("audio/")


# --------------------------------------------------------------------------
# Notes (F1, F2, F3, F4)
# --------------------------------------------------------------------------
@router.post("/notes/transcribe", dependencies=[Depends(require("clinical_draft"))])
async def transcribe_consultation(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Transcribe a consented consultation recording.

    This is the only audio path. It requires live mode; the cached demo does not
    pretend to understand audio. Consent must already exist for the encounter.
    """
    patient, encounter, _ = _state(db)
    # Every refusal below happens before credits.charge, so a refused upload spends nothing.
    consents = db.scalars(
        select(TimelineEvent).where(
            TimelineEvent.patient_id == patient.id,
            TimelineEvent.encounter_id == encounter.id,
            TimelineEvent.type == "consent",
            TimelineEvent.status == "approved",
        )
    ).all()
    if not any((event.payload or {}).get("granted") is True for event in consents):
        raise HTTPException(403, "Record patient consent before capturing audio")
    # A discharged encounter is locked, so a transcript could never become a draft: refuse before charging.
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
    # The upload is really about to run: charge before the work. The charge is only flushed, so
    # a refused upload leaves the request uncommitted and nothing is spent.
    credits.charge(db, "voice_note", feature="F1", mode="live")
    audio_id = str(uuid.uuid4())
    receipt = pipeline.submit(
        contents,
        file.filename or "consultation.webm",
        file.content_type or "audio/webm",
        audio_id,
    )
    add_audit(
        db,
        "consultation_submitted",
        "patient",
        patient.id,
        patient.id,
        actor_type="model",
        actor_name="MediBytes pipeline",
        after={"audio_id": audio_id, "job_id": receipt.get("job_id"), "encounter_id": encounter.id},
        meta={"mode": "live"},
    )
    db.commit()
    return {"audio_id": audio_id, "status": receipt.get("status", "running")}


@router.get("/notes/transcribe/{audio_id}", dependencies=[Depends(require("clinical_draft"))])
def pipeline_status(audio_id: str, db: Session = Depends(get_db)):
    """Poll the pipeline; on success the six-section note becomes an F1 draft (once per audio_id)."""
    patient, encounter, _ = _state(db)
    existing = db.scalars(
        select(TimelineEvent).where(
            TimelineEvent.patient_id == patient.id,
            TimelineEvent.type == "transcript",
            TimelineEvent.subtype == "F1",
        )
    ).all()
    for event in existing:
        if (event.payload or {}).get("audio_id") == audio_id:
            draft = db.scalars(select(Draft).where(Draft.feature == "F1", Draft.patient_id == patient.id)).all()
            match = next((d for d in draft if event.id in (d.created_from_event_ids or [])), None)
            if match:
                return {"status": "succeeded", "draft": draft_to_dict(match)}
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
    note = pipeline.parse_note(result.get("response"))
    text = pipeline.note_to_transcript(note)
    if not text:
        return {"status": "failed", "error": "No speech was detected in the recording"}
    event = create_transcript_event(db, patient, encounter, "F1", text, "Consultation (MediBytes pipeline)")
    event.payload = {**(event.payload or {}), "audio_id": audio_id, "pipeline_note": note}
    content = pipeline.to_f1_content(note, result.get("needs_review") or [], event.id)
    draft = create_draft(
        db,
        feature="F1",
        patient=patient,
        encounter=encounter,
        content=content,
        llm_call=None,
        created_from_event_ids=[event.id],
    )
    db.commit()
    return {"status": "succeeded", "draft": draft_to_dict(draft)}


@router.post("/notes/generate", dependencies=[Depends(require("clinical_draft"))])
def generate_note(body: NoteGenerateRequest, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    transcript_event = create_transcript_event(
        db,
        patient,
        encounter,
        body.feature,
        body.transcript,
        body.title or f"{body.feature} transcript",
    )
    context = build_context(
        db,
        patient,
        encounter,
        state,
        body.feature,
        transcript_event=transcript_event,
    )
    try:
        content, llm_call = generate_draft(db, body.feature, context)
    except DraftGenerationError as exc:
        db.rollback()
        raise HTTPException(502, str(exc)) from exc
    draft = create_draft(
        db,
        feature=body.feature,
        patient=patient,
        encounter=encounter,
        content=content,
        llm_call=llm_call,
        created_from_event_ids=[transcript_event.id],
    )
    db.commit()
    reason = fallback_reason(llm_call)
    return {
        "draft": draft_to_dict(draft),
        "transcript_event_id": transcript_event.id,
        "llm": {
            "mode": llm_call.mode,
            "model": llm_call.model,
            "prompt_version": llm_call.prompt_version,
            "latency_ms": llm_call.latency_ms,
            "tokens_in": llm_call.input_tokens,
            "tokens_out": llm_call.output_tokens,
            "fallback": reason is not None,
            "fallback_reason": reason,
        },
    }


@router.get("/notes/latest")
def latest_notes(feature: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Draft).order_by(Draft.created_at.desc()).limit(10)
    if feature:
        stmt = stmt.where(Draft.feature == feature)
    rows = list(db.scalars(stmt))
    return {"drafts": [draft_to_dict(draft) for draft in rows]}
