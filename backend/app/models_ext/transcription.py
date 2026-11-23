"""MediBytes async transcription jobs and their encounter associations."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from ..db import Base, utcnow
from . import resettable


@resettable
class TranscriptionJob(Base):
    __tablename__ = "transcription_jobs"

    audio_id = Column(String(64), primary_key=True)
    patient_id = Column(String, nullable=False, index=True)
    encounter_id = Column(String, nullable=False, index=True)
    company_id = Column(Integer, nullable=False, default=1)
    upload_filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    submitted_by = Column(String, nullable=False)
    job_id = Column(String)
    job_status = Column(String, nullable=False, default="queued", index=True)
    job_error = Column(Text)
    delivery_state = Column(String, nullable=False, default="pending")
    delivery_attempts = Column(Integer, nullable=False, default=0)
    delivery_last_http_status = Column(Integer)
    delivery_last_error = Column(Text)
    delivery_hims_reply = Column(Text)
    delivery_delivered_at = Column(DateTime)
    transcript_event_id = Column(String, unique=True)
    credit_charged = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    callback_received_at = Column(DateTime)
    last_status_checked_at = Column(DateTime)
