"""Persistence, API synchronization and encounter scoping for MediBytes jobs."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..config import settings
from ..dates import parse_hospital_datetime
from ..integrations import medibytes_transcription
from ..models import Draft, Encounter, Patient, TimelineEvent
from ..models_ext.transcription import TranscriptionJob
from . import credits
from .context import create_transcript_event
from .medibytes_note import MediBytesNoteError, format_note_sections, note_segments, parse_note_response
from .timeline import add_audit

JOB_STATES = {"queued", "running", "succeeded", "failed"}
DELIVERY_STATES = {"pending", "delivered", "failed", "job_failed"}
AUDIO_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
VOICE_FEATURES = {"F1", "F2", "F3", "F4", "F9", "F11"}


def safe_audio_id(value: str) -> str:
    """Map local intake IDs to MediBytes' narrower audio_id alphabet."""
    candidate = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in value)
    candidate = candidate.strip("-")[:64]
    if not candidate or not AUDIO_ID_RE.fullmatch(candidate):
        raise HTTPException(422, "audio_id must contain 1-64 letters, numbers or hyphens")
    return candidate


def get_job(db: Session, audio_id: str, patient: Patient, encounter: Encounter) -> TranscriptionJob:
    job = db.get(TranscriptionJob, audio_id)
    if not job or job.patient_id != patient.id or job.encounter_id != encounter.id:
        raise HTTPException(404, "Transcription not found for the selected consultation")
    return job


def get_intake_job(db: Session, intake_id: str) -> TranscriptionJob:
    job = db.scalars(select(TranscriptionJob).where(TranscriptionJob.intake_id == intake_id)).first()
    if not job:
        raise HTTPException(404, "Intake transcription not found")
    return job


def list_jobs(db: Session, patient: Patient, encounter: Encounter) -> list[TranscriptionJob]:
    return list(
        db.scalars(
            select(TranscriptionJob)
            .where(TranscriptionJob.patient_id == patient.id, TranscriptionJob.encounter_id == encounter.id)
            .order_by(TranscriptionJob.created_at.desc(), TranscriptionJob.audio_id)
        )
    )


def charge_once(db: Session, job: TranscriptionJob) -> None:
    if job.credit_charged:
        return
    credits.charge(
        db,
        "voice_note",
        feature=job.feature or "F1",
        mode="medibytes",
        patient_id=job.patient_id,
        actor=job.submitted_by,
    )
    job.credit_charged = True


def _review_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        section, text = item.get("section"), item.get("text")
        if isinstance(section, str) and isinstance(text, str):
            result.append({"section": section, "text": text})
    return result


def _store_contract(job: TranscriptionJob, note: dict[str, str], response: str, needs_review: Any = None) -> None:
    job.note_content = json.dumps(note, ensure_ascii=False)
    if not job.raw_response:
        job.raw_response = response
    if needs_review is not None:
        incoming = _review_items(needs_review)
        current = _load_json(job.needs_review, [])
        if incoming or not current:
            job.needs_review = json.dumps(incoming, ensure_ascii=False)
    elif job.needs_review is None:
        job.needs_review = "[]"


def _load_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def save_transcript(
    db: Session,
    job: TranscriptionJob,
    response: str,
    *,
    source: str = "callback",
    needs_review: Any = None,
) -> tuple[TimelineEvent | None, bool]:
    """Validate and persist a note once; intake jobs wait for patient registration to create an event."""
    note = parse_note_response(response)
    previous_note = _load_json(job.note_content, None)
    is_duplicate = previous_note == note
    if previous_note is not None and previous_note != note:
        raise HTTPException(409, "A different transcript is already saved for this audio_id")
    if job.transcript_event_id:
        event = db.get(TimelineEvent, job.transcript_event_id)
        event_note = (event.payload or {}).get("note_content") if event else None
        if event and event_note != note:
            raise HTTPException(409, "A different transcript is already saved for this audio_id")
    else:
        event = None

    _store_contract(job, note, response, needs_review)
    job.job_status = "succeeded"
    job.job_error = None
    if source == "callback":
        job.delivery_state = "delivered"
        job.delivery_delivered_at = job.delivery_delivered_at or clock.now()
        job.delivery_next_attempt_at = None
        job.callback_received_at = job.callback_received_at or clock.now()

    if job.intake_id:
        charge_once(db, job)
        return None, is_duplicate

    if event:
        event.payload = {
            **(event.payload or {}),
            "note_content": note,
            "needs_review": _load_json(job.needs_review, []),
            "raw_response": (event.payload or {}).get("raw_response") if is_duplicate else response,
        }
        charge_once(db, job)
        return event, True

    from .timeline import get_encounter, get_patient

    patient = get_patient(db, job.patient_id)
    encounter = get_encounter(db, job.encounter_id)
    if encounter.patient_id != patient.id:
        raise HTTPException(409, "Transcription association no longer matches its consultation")
    display_text = format_note_sections(note)
    feature = job.feature if job.feature in VOICE_FEATURES else "F1"
    title = {
        "F1": "Consultation",
        "F2": "Admission dictation",
        "F3": "Ward-round dictation",
        "F4": "Progress note dictation",
        "F9": "Discharge dictation",
        "F11": "Referral dictation",
    }[feature]
    event = create_transcript_event(
        db, patient, encounter, feature, display_text, f"MediBytes {title} · {job.audio_id[:8]}"
    )
    event.payload = {
        "feature": feature,
        "segments": note_segments(note),
        "note_content": note,
        "needs_review": _load_json(job.needs_review, []),
        "raw_response": response,
        "audio_id": job.audio_id,
        "role": job.role,
    }
    event.source = "medibytes"
    event.author_type = "model"
    event.author_name = "MediBytes Transcription API"
    event.approved_by = None
    event.occurred_at = job.created_at
    job.transcript_event_id = event.id
    charge_once(db, job)
    add_audit(
        db,
        "consultation_transcribed",
        "patient",
        patient.id,
        patient.id,
        actor_type="model",
        actor_name="MediBytes Transcription API",
        after={"characters": len(response), "encounter_id": encounter.id, "audio_id": job.audio_id, "feature": feature},
        meta={"mode": "medibytes", "transcript_event_id": event.id, "source": source, "sections": len(note)},
    )
    return event, False


def apply_api_status(db: Session, job: TranscriptionJob, payload: dict[str, Any]) -> None:
    job_state = payload.get("job_status")
    if job_state in JOB_STATES and not (job.transcript_event_id and job_state != "succeeded"):
        job.job_status = job_state
    job.job_id = payload.get("job_id") or job.job_id
    job.job_error = payload.get("job_error")

    delivery = payload.get("delivery")
    if isinstance(delivery, dict):
        state = delivery.get("state")
        if state in DELIVERY_STATES:
            job.delivery_state = state
        attempts = delivery.get("attempts")
        if isinstance(attempts, int) and attempts >= 0:
            job.delivery_attempts = attempts
        status_code = delivery.get("last_http_status")
        if isinstance(status_code, int):
            job.delivery_last_http_status = status_code
        job.delivery_last_error = delivery.get("last_error")
        reply = delivery.get("hims_reply")
        job.delivery_hims_reply = reply if isinstance(reply, str) else None
        delivered_at = parse_hospital_datetime(delivery.get("delivered_at"))
        if delivered_at:
            job.delivery_delivered_at = delivered_at
        job.delivery_next_attempt_at = parse_hospital_datetime(delivery.get("next_attempt_at"))

    response = payload.get("response")
    review = payload.get("needs_review")
    if isinstance(response, str) and response.strip():
        try:
            save_transcript(db, job, response, source="status", needs_review=review)
        except MediBytesNoteError as exc:
            job.job_error = str(exc)
        except HTTPException as exc:
            job.job_error = str(exc.detail)
    elif review is not None:
        review_items = _review_items(review)
        existing_review = _load_json(job.needs_review, [])
        if review_items or not existing_review:
            job.needs_review = json.dumps(review_items, ensure_ascii=False)
        event = db.get(TimelineEvent, job.transcript_event_id) if job.transcript_event_id else None
        if event and (review_items or not (event.payload or {}).get("needs_review")):
            event.payload = {**(event.payload or {}), "needs_review": review_items}
    if job.job_status == "succeeded" and not job.transcript_event_id and not job.intake_id and not (isinstance(response, str) and response.strip()):
        job.job_error = "MediBytes marked the job succeeded but has not returned a transcript yet."
    if job.job_status in {"queued", "running", "succeeded"}:
        charge_once(db, job)
    job.last_status_checked_at = clock.now()


def job_to_dict(db: Session, job: TranscriptionJob, *, status_check_error: str | None = None) -> dict[str, Any]:
    event = db.get(TimelineEvent, job.transcript_event_id) if job.transcript_event_id else None
    event_payload = (event.payload or {}) if event else {}
    note_content = event_payload.get("note_content") or _load_json(job.note_content, None)
    review = event_payload.get("needs_review")
    if review is None:
        review = _load_json(job.needs_review, [])
    return {
        "audio_id": job.audio_id,
        "intake_id": job.intake_id,
        "encounter_id": job.encounter_id,
        "feature": job.feature or "F1",
        "role": job.role,
        "filename": job.upload_filename,
        "job_id": job.job_id,
        "job_status": job.job_status,
        "job_error": job.job_error,
        "delivery": {
            "state": job.delivery_state,
            "attempts": job.delivery_attempts,
            "last_http_status": job.delivery_last_http_status,
            "last_error": job.delivery_last_error,
            "hims_reply": job.delivery_hims_reply,
            "delivered_at": job.delivery_delivered_at.isoformat() if job.delivery_delivered_at else None,
            "next_attempt_at": job.delivery_next_attempt_at.isoformat() if job.delivery_next_attempt_at else None,
        },
        "transcript": event.body_text if event else (format_note_sections(note_content) if note_content else None),
        "note_content": note_content,
        "needs_review": review,
        "response": event_payload.get("raw_response") or job.raw_response,
        "transcript_event_id": event.id if event else None,
        "draft_id": job.draft_id,
        "can_redeliver": job.job_status == "succeeded" and job.delivery_state == "failed",
        "credit_charged": job.credit_charged,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "status_check_error": status_check_error,
    }


def create_report_draft(db: Session, job: TranscriptionJob) -> Draft | None:
    """Create the feature report once the six-section note has been saved."""
    if job.intake_id or not job.transcript_event_id or job.job_status != "succeeded":
        return None
    if job.draft_id:
        return db.get(Draft, job.draft_id)

    event = db.get(TimelineEvent, job.transcript_event_id)
    if not event:
        return None
    for draft in db.scalars(
        select(Draft).where(
            Draft.patient_id == job.patient_id,
            Draft.encounter_id == job.encounter_id,
            Draft.feature == job.feature,
        ).order_by(Draft.created_at.desc())
    ):
        if event.id in (draft.created_from_event_ids or []):
            job.draft_id = draft.id
            db.commit()
            return draft

    note = (event.payload or {}).get("note_content") or _load_json(job.note_content, None)
    if not isinstance(note, dict):
        return None
    from .drafts import create_draft
    from .report_templates import generate_report_template
    from .timeline import get_encounter, get_patient

    patient = get_patient(db, job.patient_id)
    encounter = get_encounter(db, job.encounter_id)
    content, llm_call = generate_report_template(
        db,
        job.feature,
        note,
        (event.payload or {}).get("needs_review") or _load_json(job.needs_review, []),
        event.id,
    )
    if job.feature == "F4" and job.role:
        content["role"] = job.role
    draft = create_draft(
        db,
        feature=job.feature,
        patient=patient,
        encounter=encounter,
        content=content,
        llm_call=llm_call,
        created_from_event_ids=[event.id],
        voice_template=True,
    )
    job.draft_id = draft.id
    db.commit()
    return draft


async def submit_transcription(
    db: Session,
    *,
    audio_id: str,
    patient_id: str,
    encounter_id: str,
    feature: str,
    filename: str,
    content_type: str,
    audio: bytes,
    submitted_by: str,
    role: str | None = None,
    intake_id: str | None = None,
) -> dict[str, Any]:
    """Create a local association and submit through the sole MediBytes HTTP client."""
    if feature not in VOICE_FEATURES:
        raise HTTPException(422, f"Voice is not available for {feature}")
    if not settings.medibytes_api_key:
        raise HTTPException(503, "MediBytes transcription is not configured (MEDIBYTES_API_KEY is missing).")
    audio_id = safe_audio_id(audio_id)
    existing = db.get(TranscriptionJob, audio_id)
    if existing:
        if (existing.patient_id, existing.encounter_id, existing.feature, existing.intake_id, existing.role) != (patient_id, encounter_id, feature, intake_id, role):
            raise HTTPException(409, "audio_id is already associated with another recording")
        if existing.job_status in {"queued", "running", "succeeded"}:
            return job_to_dict(db, existing)
        existing.upload_filename = filename.rsplit("/", 1)[-1]
        existing.content_type = content_type
        existing.job_status = "queued"
        existing.job_error = None
    else:
        existing = TranscriptionJob(
            audio_id=audio_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            feature=feature,
            role=role,
            intake_id=intake_id,
            company_id=settings.medibytes_company_id,
            upload_filename=filename.rsplit("/", 1)[-1],
            content_type=content_type,
            submitted_by=submitted_by,
            job_status="queued",
            delivery_state="pending",
        )
        db.add(existing)

    if credits.status(db)["balance"] < credits.SCHEDULE["voice_note"] and not existing.credit_charged:
        db.rollback()
        raise HTTPException(402, "Voice note needs 2 credits; add a pack to continue.")

    # Commit the association before upload so a fast callback can resolve it.
    db.commit()
    try:
        acknowledgement = await medibytes_transcription.upload_audio(
            audio_id,
            existing.company_id,
            existing.upload_filename,
            existing.content_type,
            audio,
        )
    except medibytes_transcription.MediBytesRequestError as exc:
        existing.job_error = str(exc)
        if exc.status_code not in {502, 504}:
            existing.job_status = "failed"
        db.commit()
        raise HTTPException(exc.status_code, str(exc)) from exc

    existing.job_id = acknowledgement.get("job_id") or existing.job_id
    external_state = acknowledgement.get("status")
    if not existing.transcript_event_id and existing.job_status != "succeeded":
        existing.job_status = external_state if external_state in JOB_STATES else "queued"
    existing.job_error = None if existing.transcript_event_id else existing.job_error
    existing.delivery_state = "pending" if not existing.transcript_event_id else existing.delivery_state
    charge_once(db, existing)
    db.commit()
    return job_to_dict(db, existing)


async def refresh_transcription_status(db: Session, job: TranscriptionJob) -> str | None:
    """Poll MediBytes and synchronize the local record, returning a non-fatal poll error."""
    status_error = None
    try:
        payload = await medibytes_transcription.get_audio_status(job.audio_id)
        apply_api_status(db, job, payload)
    except medibytes_transcription.MediBytesRequestError as exc:
        status_error = str(exc)
        job.last_status_checked_at = clock.now()
        if exc.status_code == 404:
            job.job_status = "failed"
            job.job_error = str(exc)
    db.commit()
    return status_error


async def redeliver_transcription(db: Session, job: TranscriptionJob) -> dict[str, Any]:
    """Refresh delivery state and request one redelivery only for a failed delivery."""
    try:
        latest = await medibytes_transcription.get_audio_status(job.audio_id)
        apply_api_status(db, job, latest)
        db.commit()
        if job.delivery_state != "failed":
            raise HTTPException(409, "Transcript delivery has not failed")
        await medibytes_transcription.redeliver_transcript(job.audio_id)
    except medibytes_transcription.MediBytesRequestError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from exc
    job.delivery_state = "pending"
    job.delivery_last_error = None
    job.delivery_hims_reply = None
    job.delivery_next_attempt_at = None
    db.commit()
    return job_to_dict(db, job)
