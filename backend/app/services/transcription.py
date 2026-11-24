"""Persistence and encounter scoping for MediBytes transcription jobs."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..dates import parse_hospital_datetime
from ..models import Encounter, Patient, TimelineEvent
from ..models_ext.transcription import TranscriptionJob
from . import credits
from .context import create_transcript_event
from .medibytes_note import (
    MediBytesNoteError,
    format_note_sections,
    note_segments,
    parse_note_response,
)
from .timeline import add_audit

JOB_STATES = {"queued", "running", "succeeded", "failed"}
DELIVERY_STATES = {"pending", "delivered", "failed", "job_failed"}


def get_job(
    db: Session,
    audio_id: str,
    patient: Patient,
    encounter: Encounter,
) -> TranscriptionJob:
    job = db.get(TranscriptionJob, audio_id)
    if not job or job.patient_id != patient.id or job.encounter_id != encounter.id:
        raise HTTPException(404, "Transcription not found for the selected consultation")
    return job


def list_jobs(db: Session, patient: Patient, encounter: Encounter) -> list[TranscriptionJob]:
    return list(
        db.scalars(
            select(TranscriptionJob)
            .where(
                TranscriptionJob.patient_id == patient.id,
                TranscriptionJob.encounter_id == encounter.id,
            )
            .order_by(TranscriptionJob.created_at.desc(), TranscriptionJob.audio_id)
        )
    )


def charge_once(db: Session, job: TranscriptionJob) -> None:
    if job.credit_charged:
        return
    credits.charge(
        db,
        "voice_note",
        feature="F1",
        mode="medibytes",
        patient_id=job.patient_id,
        actor=job.submitted_by,
    )
    job.credit_charged = True


def save_transcript(
    db: Session, job: TranscriptionJob, response: str, *, source: str = "callback"
) -> tuple[TimelineEvent, bool]:
    """Validate and persist MediBytes' six-section note once for the original consultation."""
    note = parse_note_response(response)
    if job.transcript_event_id:
        event = db.get(TimelineEvent, job.transcript_event_id)
        event_note = (event.payload or {}).get("note_content") if event else None
        if event and event_note == note:
            job.job_status = "succeeded"
            job.job_error = None
            if source == "callback":
                job.delivery_state = "delivered"
                job.delivery_delivered_at = job.delivery_delivered_at or clock.now()
                job.delivery_next_attempt_at = None
                job.callback_received_at = job.callback_received_at or clock.now()
            charge_once(db, job)
            return event, True
        if event:
            raise HTTPException(409, "A different transcript is already saved for this audio_id")

    from .timeline import get_encounter, get_patient

    patient = get_patient(db, job.patient_id)
    encounter = get_encounter(db, job.encounter_id)
    if encounter.patient_id != patient.id:
        raise HTTPException(409, "Transcription association no longer matches its consultation")
    display_text = format_note_sections(note)
    event = create_transcript_event(
        db,
        patient,
        encounter,
        "F1",
        display_text,
        f"MediBytes consultation note · {job.audio_id[:8]}",
    )
    event.payload = {
        "feature": "F1",
        "segments": note_segments(note),
        "note_content": note,
        "raw_response": response,
    }
    event.source = "medibytes"
    event.author_type = "model"
    event.author_name = "MediBytes Transcription API"
    event.approved_by = None
    event.occurred_at = job.created_at
    job.transcript_event_id = event.id
    job.job_status = "succeeded"
    job.job_error = None
    if source == "callback":
        job.delivery_state = "delivered"
        job.delivery_delivered_at = job.delivery_delivered_at or clock.now()
        job.delivery_next_attempt_at = None
        job.callback_received_at = clock.now()
    charge_once(db, job)
    add_audit(
        db,
        "consultation_transcribed",
        "patient",
        patient.id,
        patient.id,
        actor_type="model",
        actor_name="MediBytes MedASR",
        after={"characters": len(response), "encounter_id": encounter.id, "audio_id": job.audio_id},
        meta={"mode": "medibytes", "transcript_event_id": event.id, "source": source, "sections": len(note)},
    )
    return event, False


def apply_api_status(db: Session, job: TranscriptionJob, payload: dict[str, Any]) -> None:
    job_state = payload.get("job_status")
    if job_state in JOB_STATES:
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
    if isinstance(response, str) and response.strip() and not job.transcript_event_id:
        try:
            save_transcript(db, job, response, source="status")
        except MediBytesNoteError as exc:
            job.job_error = str(exc)
    elif job.job_status == "succeeded" and not job.transcript_event_id:
        job.job_error = "MediBytes marked the job succeeded but has not returned a transcript yet."
    elif job.job_status in {"queued", "running", "succeeded"}:
        charge_once(db, job)
    job.last_status_checked_at = clock.now()


def job_to_dict(db: Session, job: TranscriptionJob, *, status_check_error: str | None = None) -> dict[str, Any]:
    event = db.get(TimelineEvent, job.transcript_event_id) if job.transcript_event_id else None
    event_payload = (event.payload or {}) if event else {}
    return {
        "audio_id": job.audio_id,
        "encounter_id": job.encounter_id,
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
        "transcript": event.body_text if event else None,
        "note_content": event_payload.get("note_content"),
        "response": event_payload.get("raw_response"),
        "transcript_event_id": event.id if event else None,
        "can_redeliver": job.job_status == "succeeded" and job.delivery_state == "failed",
        "credit_charged": job.credit_charged,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "status_check_error": status_check_error,
    }
