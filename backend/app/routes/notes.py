from __future__ import annotations

import hmac
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Draft, TimelineEvent
from ..models_ext.transcription import TranscriptionJob
from ..services.identity import acting_name, acting_user, can, require
from ..services.context import build_context, create_transcript_event
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.llm import DraftGenerationError, fallback_reason, generate_draft
from ..services.report_templates import generate_report_template
from ..services.timeline import (
    require_open_encounter,
)
from ..services.transcription import (
    create_report_draft,
    get_job,
    job_to_dict,
    list_jobs,
    redeliver_transcription,
    refresh_transcription_status,
    save_transcript,
    submit_transcription,
)
from ..services.medibytes_note import MediBytesNoteError
from .common import (
    NoteGenerateRequest,
    _patient_encounter,
    _state,
)

router = APIRouter()

MAX_AUDIO_BYTES = 64 * 1024 * 1024
AUDIO_EXTENSIONS = {"wav", "mp3", "m4a", "mp4", "aac", "flac", "ogg", "webm"}
AUDIO_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")


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
@router.post("/notes/transcribe", dependencies=[Depends(require("transcribe_voice"))])
async def transcribe_consultation(
    file: UploadFile = File(...),
    feature: str = Form("F1"),
    role: str = Form(""),
    encounter_id: str | None = Query(default=None),
    audio_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Submit any consultation or ward recording through the shared MediBytes client."""
    patient, encounter = _patient_encounter(db, encounter_id)
    user = acting_user()
    if feature == "F4":
        from ..services import progress
        resolved_role = role or progress.default_role()
        if resolved_role not in progress.ROLES or not progress.may_write(resolved_role):
            raise HTTPException(403, "You cannot write this progress-note table")
        role = resolved_role
    elif feature == "F11":
        if not can("refer", user):
            raise HTTPException(403, "You may not create referrals")
    elif feature == "F9":
        if not can("discharge_report", user):
            raise HTTPException(403, "You may not create discharge reports")
    elif not can("clinical_draft", user):
        raise HTTPException(403, "You may not create clinical drafts")
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
    if feature not in {"F1", "F2", "F3", "F4", "F9", "F11"}:
        raise HTTPException(422, f"Voice is not available for {feature}")
    if not _looks_like_audio(file.filename, file.content_type):
        raise HTTPException(415, "Unsupported audio type. Upload wav, mp3, m4a, mp4, aac, flac, ogg or webm.")
    contents = await file.read(MAX_AUDIO_BYTES + 1)
    if len(contents) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio too large (max 64 MB)")
    if not contents:
        raise HTTPException(400, "The audio file is empty")

    return await submit_transcription(
        db,
        audio_id=audio_id or str(uuid.uuid4()),
        patient_id=patient.id,
        encounter_id=encounter.id,
        feature=feature,
        role=role or None,
        filename=file.filename or "consultation.audio",
        content_type=file.content_type or "application/octet-stream",
        audio=contents,
        submitted_by=acting_name(),
    )


class MediBytesCallback(BaseModel):
    audio_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    company_id: int
    response: str
    needs_review: list[dict[str, str]] | None = None


@router.post("/transcriptions/callback")
def receive_transcript(
    body: MediBytesCallback,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Receive and validate MediBytes' six-section note with a separately configured HIMS token."""
    if not settings.medibytes_callback_token:
        raise HTTPException(503, "MediBytes callback authentication is not configured")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or not hmac.compare_digest(token, settings.medibytes_callback_token):
        raise HTTPException(401, "Unauthorized")
    job = db.get(TranscriptionJob, body.audio_id)
    if not job:
        return JSONResponse(status_code=200, content={"status": "Failed", "Message": "Transcription record not found"})
    if body.company_id != job.company_id:
        return JSONResponse(
            status_code=200,
            content={"status": "Failed", "Message": "company_id does not match the transcription record"},
        )
    try:
        save_transcript(db, job, body.response, needs_review=body.needs_review)
    except MediBytesNoteError as exc:
        db.rollback()
        return JSONResponse(status_code=200, content={"status": "Failed", "Message": str(exc)})
    except HTTPException as exc:
        db.rollback()
        return JSONResponse(status_code=200, content={"status": "Failed", "Message": str(exc.detail)})
    db.commit()
    return {"status": "Success"}


@router.get("/notes/transcriptions", dependencies=[Depends(require("transcribe_voice"))])
def consultation_transcriptions(
    encounter_id: str | None = Query(default=None), db: Session = Depends(get_db)
):
    patient, encounter = _patient_encounter(db, encounter_id)
    return {"transcriptions": [job_to_dict(db, job) for job in list_jobs(db, patient, encounter)]}


@router.get("/notes/transcriptions/{audio_id}", dependencies=[Depends(require("transcribe_voice"))])
async def consultation_transcription_status(
    audio_id: str,
    encounter_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    patient, encounter = _patient_encounter(db, encounter_id)
    job = get_job(db, audio_id, patient, encounter)
    status_error = await refresh_transcription_status(db, job)
    result = job_to_dict(db, job, status_check_error=status_error)
    result["can_retry_upload"] = job.job_status == "failed" and not job.transcript_event_id
    draft = create_report_draft(db, job)
    if draft:
        result["draft"] = draft_to_dict(draft)
    return result


@router.get("/notes/transcribe/{audio_id}", dependencies=[Depends(require("transcribe_voice"))])
async def legacy_transcription_status(
    audio_id: str,
    encounter_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Compatibility poll route; new clients use /notes/transcriptions/{audio_id}."""
    patient, encounter = _patient_encounter(db, encounter_id)
    job = get_job(db, audio_id, patient, encounter)
    status_error = await refresh_transcription_status(db, job)
    draft = create_report_draft(db, job)
    result = {"status": job.job_status, "error": job.job_error, "status_check_error": status_error}
    if draft:
        result["draft"] = draft_to_dict(draft)
    return result


@router.post("/notes/transcriptions/{audio_id}/redeliver", dependencies=[Depends(require("transcribe_voice"))])
async def redeliver_consultation_transcript(
    audio_id: str,
    encounter_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    patient, encounter = _patient_encounter(db, encounter_id)
    job = get_job(db, audio_id, patient, encounter)
    return await redeliver_transcription(db, job)


@router.post("/notes/generate", dependencies=[Depends(require("transcribe_voice"))])
def generate_note(
    body: NoteGenerateRequest,
    encounter_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    patient, encounter = _patient_encounter(db, encounter_id)
    user = acting_user()
    if body.feature == "F4":
        from ..services import progress
        if not progress.may_write(progress.default_role()):
            raise HTTPException(403, "You cannot write this progress-note table")
    elif body.feature == "F11":
        if not can("refer", user):
            raise HTTPException(403, "You may not create referrals")
    elif body.feature == "F9":
        if not can("discharge_report", user):
            raise HTTPException(403, "You may not create discharge reports")
    elif not can("clinical_draft", user):
        raise HTTPException(403, "You may not create clinical drafts")
    state = _state(db, encounter.id)[2]
    if body.transcript_event_id:
        transcript_event = db.get(TimelineEvent, body.transcript_event_id)
        if (
            not transcript_event
            or transcript_event.patient_id != patient.id
            or transcript_event.encounter_id != encounter.id
            or transcript_event.type != "transcript"
            or transcript_event.subtype != body.feature
            or transcript_event.body_text != body.transcript
        ):
            raise HTTPException(404, "Transcript not found for the selected consultation")
    else:
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
        note = (transcript_event.payload or {}).get("note_content")
        if isinstance(note, dict):
            content, llm_call = generate_report_template(
                db,
                body.feature,
                note,
                (transcript_event.payload or {}).get("needs_review") or [],
                transcript_event.id,
            )
            if body.feature == "F4" and (transcript_event.payload or {}).get("role"):
                content["role"] = (transcript_event.payload or {}).get("role")
        else:
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
            voice_template=isinstance(note, dict),
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
def latest_notes(feature: str | None = None, encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter = _patient_encounter(db, encounter_id)
    stmt = select(Draft).where(Draft.patient_id == patient.id, Draft.encounter_id == encounter.id).order_by(Draft.created_at.desc()).limit(10)
    if feature:
        stmt = stmt.where(Draft.feature == feature)
    rows = list(db.scalars(stmt))
    return {"drafts": [draft_to_dict(draft) for draft in rows]}
