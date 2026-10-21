"""Tables for the hospital-system link: what came in and what is waiting to go out."""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text

from ..db import Base, utcnow
from . import resettable


@resettable
class IntegrationSync(Base):
    """One inbound exchange (a posted bundle or a pull) and how it went."""

    __tablename__ = "integration_syncs"

    id = Column(String, primary_key=True)
    system = Column(String, nullable=False)
    kind = Column(String, default="inbound")  # inbound | pull
    status = Column(String, default="ok")  # ok | partial | failed
    created = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    detail = Column(JSON, default=list)
    patient_id = Column(String)
    started_at = Column(DateTime, default=utcnow)
    finished_at = Column(DateTime)


@resettable
class OutboundMessage(Base):
    """A FHIR resource waiting to be sent to the hospital system."""

    __tablename__ = "outbound_messages"

    id = Column(String, primary_key=True)
    system = Column(String, default="hospital")
    resource_type = Column(String, nullable=False)
    payload = Column(JSON, default=dict)
    status = Column(String, default="queued", index=True)  # queued | sent | failed | not_configured
    attempts = Column(Integer, default=0)
    last_error = Column(Text)
    patient_id = Column(String)
    source_event_id = Column(String)
    created_at = Column(DateTime, default=utcnow)
    sent_at = Column(DateTime)
    next_attempt_at = Column(DateTime)
