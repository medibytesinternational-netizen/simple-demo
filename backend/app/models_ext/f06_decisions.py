"""F6: one clinician decision on one medication reconciliation discrepancy."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, String, Text

from ..db import Base, utcnow
from . import resettable


@resettable
class ReconciliationDecision(Base):
    __tablename__ = "f06_reconciliation_decisions"

    id = Column(String, primary_key=True)
    patient_id = Column(String, nullable=False, index=True)
    encounter_id = Column(String, nullable=False, index=True)
    discrepancy_id = Column(String, nullable=False, index=True)
    decision = Column(String, nullable=False)  # continue | hold | stop | change
    note = Column(Text, nullable=False, default="")
    decided_by = Column(String, nullable=False)
    decided_at = Column(DateTime, default=utcnow)
    # Facts the decision was made on; when they change the item opens again.
    fingerprint = Column(String, nullable=False, default="")
