from __future__ import annotations


from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import (
    Draft,
    TimelineEvent,
)
from ..services import credits
from ..services.identity import require
from ..services.context import build_context, create_transcript_event
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.llm import DraftGenerationError, fallback_reason, generate_draft
from ..services.timeline import (
    add_audit,
)
from .common import (
    NoteGenerateRequest,
    _state,
)

router = APIRouter()


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
    if not settings.openai_api_key:
        raise HTTPException(400, "Live transcription requires OPENAI_API_KEY; use the seeded transcript in cached mode")
    contents = await file.read()
    if len(contents) > 25 * 1024 * 1024:
        raise HTTPException(400, "Audio too large (max 25 MB)")
    # A transcription is really about to run: charge before the work. The charge is only flushed, so
    # a failed transcription leaves the request uncommitted and nothing is spent.
    credits.charge(db, "voice_note", feature="F1", mode="live")
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=(file.filename or "consultation.webm", contents, file.content_type or "audio/webm"),
        )
        text = str(getattr(transcript, "text", "") or "").strip()
    except Exception as exc:
        raise HTTPException(502, f"Transcription failed: {exc}") from exc
    if not text:
        raise HTTPException(422, "No speech was detected in the recording")
    add_audit(
        db,
        "consultation_transcribed",
        "patient",
        patient.id,
        patient.id,
        actor_type="model",
        actor_name="whisper-1",
        after={"characters": len(text), "encounter_id": encounter.id},
        meta={"mode": "live"},
    )
    db.commit()
    return {"text": text, "model": "whisper-1"}


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
