from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy import JSON

from .db import Base, utcnow


class Patient(Base):
    __tablename__ = "patients"

    id = Column(String, primary_key=True)
    mrn = Column(String, nullable=False)
    name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    sex = Column(String, nullable=False)
    allergies = Column(JSON, default=list)
    problems = Column(JSON, default=list)
    weight_kg = Column(Float)
    height_cm = Column(Float)
    code_status = Column(String, default="Full code")
    created_at = Column(DateTime, default=utcnow)


class Encounter(Base):
    __tablename__ = "encounters"

    id = Column(String, primary_key=True)
    patient_id = Column(String, nullable=False, index=True)
    kind = Column(String, default="IPD")
    ward = Column(String)
    bed = Column(String)
    attending = Column(String)
    admitted_at = Column(DateTime)
    discharged_at = Column(DateTime)
    status = Column(String, default="active")
    created_at = Column(DateTime, default=utcnow)


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id = Column(String, primary_key=True)
    patient_id = Column(String, nullable=False, index=True)
    encounter_id = Column(String, nullable=True, index=True)
    type = Column(String, nullable=False)
    subtype = Column(String)
    title = Column(String, nullable=False)
    body_text = Column(Text)
    payload = Column(JSON, default=dict)
    source = Column(String, default="seed")
    author_type = Column(String, default="system")
    author_name = Column(String, default="System")
    status = Column(String, default="approved")
    confidence = Column(Float)
    supersedes_event_id = Column(String)
    occurred_at = Column(DateTime, default=utcnow)
    created_at = Column(DateTime, default=utcnow)
    approved_by = Column(String)
    approved_at = Column(DateTime)
    document_id = Column(String)


class Draft(Base):
    __tablename__ = "drafts"

    id = Column(String, primary_key=True)
    feature = Column(String, nullable=False, index=True)
    patient_id = Column(String, nullable=False)
    encounter_id = Column(String)
    status = Column(String, default="draft_ready")
    content = Column(JSON, default=dict)
    schema_version = Column(String, default="v1")
    prompt_version = Column(String, default="v1")
    model = Column(String)
    llm_call_id = Column(String)
    evidence_event_ids = Column(JSON, default=list)
    created_from_event_ids = Column(JSON, default=list)
    edited_by = Column(String)
    approved_by = Column(String)
    rejected_reason = Column(String)
    committed_event_id = Column(String)
    idempotency_key = Column(String)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    patient_id = Column(String, nullable=False)
    encounter_id = Column(String)
    title = Column(String, nullable=False)
    detail = Column(Text)
    status = Column(String, default="proposed")
    priority = Column(String, default="routine")
    due_at = Column(DateTime)
    owner = Column(String)
    source_event_id = Column(String)
    accepted_from_draft_id = Column(String)
    completed_at = Column(DateTime)
    created_by = Column(String)
    created_at = Column(DateTime, default=utcnow)
    assigned_to = Column(String)
    assigned_at = Column(DateTime)
    assigned_by = Column(String)
    acknowledged_at = Column(DateTime)
    acknowledged_by = Column(String)
    escalation_level = Column(Integer, default=0)
    escalated_at = Column(DateTime)
    escalation_reason = Column(Text)
    # Ward-round tasking: what kind of work, which role it is for, and its place in the queue.
    category = Column(String, default="general")
    assignee_role = Column(String)
    queue_rank = Column(Integer, default=0)
    completion_event_id = Column(String)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True)
    patient_id = Column(String, nullable=False)
    encounter_id = Column(String)
    rule_id = Column(String, nullable=False)
    dedupe_key = Column(String, unique=True)
    severity = Column(String, default="warning")
    status = Column(String, default="open")
    title = Column(String, nullable=False)
    explanation = Column(Text)
    recommended_action = Column(Text)
    evidence_event_ids = Column(JSON, default=list)
    acknowledged_by = Column(String)
    dismissed_by = Column(String)
    dismissal_reason = Column(Text)
    dismissal_category = Column(String)
    resolution = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    resolved_at = Column(DateTime)


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True)
    patient_id = Column(String, nullable=False)
    encounter_id = Column(String)
    filename = Column(String)
    mime = Column(String)
    path = Column(String)
    image_kind = Column(String, default="file")
    doc_type = Column(String, default="lab_report")
    ocr_status = Column(String, default="pending")
    raw_text = Column(Text)
    extracted = Column(JSON, default=dict)
    uploaded_by = Column(String)
    uploaded_at = Column(DateTime, default=utcnow)
    confirmed_by = Column(String)
    confirmed_at = Column(DateTime)


class DocumentRequest(Base):
    __tablename__ = "document_requests"

    id = Column(String, primary_key=True)
    patient_id = Column(String, nullable=False)
    encounter_id = Column(String)
    request_type = Column(String, default="records")
    records_requested = Column(JSON, default=list)
    recipient = Column(String)
    justification = Column(Text)
    due_at = Column(DateTime)
    status = Column(String, default="draft")
    matched_document_id = Column(String)
    draft_id = Column(String)
    created_at = Column(DateTime, default=utcnow)
    approved_by = Column(String)


class InvestigationRequest(Base):
    __tablename__ = "investigation_requests"

    id = Column(String, primary_key=True)
    patient_id = Column(String, nullable=False)
    encounter_id = Column(String)
    request_type = Column(String, default="laboratory")
    study = Column(String)
    indication = Column(Text)
    diagnosis = Column(Text)
    allergies_to_verify = Column(JSON, default=list)
    priority = Column(String, default="routine")
    instructions = Column(Text)
    status = Column(String, default="approved")
    draft_id = Column(String)
    approved_by = Column(String)
    created_at = Column(DateTime, default=utcnow)
    exported_at = Column(DateTime)


class Referral(Base):
    __tablename__ = "referrals"

    id = Column(String, primary_key=True)
    patient_id = Column(String, nullable=False)
    encounter_id = Column(String)
    specialty = Column(String)
    specialist = Column(String)
    question = Column(Text)
    history = Column(Text)
    urgency = Column(String, default="routine")
    status = Column(String, default="sent")
    draft_id = Column(String)
    approved_by = Column(String)
    sent_at = Column(DateTime)
    acknowledged_at = Column(DateTime)
    completed_at = Column(DateTime)
    response_summary = Column(Text)
    consult_event_id = Column(String)
    created_at = Column(DateTime, default=utcnow)


class BillLineItem(Base):
    __tablename__ = "bill_line_items"

    id = Column(String, primary_key=True)
    patient_id = Column(String, nullable=False)
    encounter_id = Column(String)
    code = Column(String)
    description = Column(String)
    amount = Column(Float, default=0)
    expected_amount = Column(Float)
    billed_at = Column(DateTime, default=utcnow)
    documentation_event_ids = Column(JSON, default=list)


class ClaimReview(Base):
    __tablename__ = "claim_reviews"

    id = Column(String, primary_key=True)
    patient_id = Column(String, nullable=False)
    encounter_id = Column(String)
    status = Column(String, default="draft")
    prepared_at = Column(DateTime)
    reviewed_by = Column(String)
    created_at = Column(DateTime, default=utcnow)


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id = Column(String, primary_key=True)
    feature = Column(String, nullable=False)
    prompt_version = Column(String, default="v1")
    prompt_hash = Column(String)
    model = Column(String)
    temperature = Column(Float, default=0.1)
    context_hash = Column(String)
    request_json = Column(JSON, default=dict)
    response_json = Column(JSON, default=dict)
    status = Column(String, default="ok")
    validation_errors = Column(JSON, default=list)
    latency_ms = Column(Integer, default=0)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    mode = Column(String, default="cached")
    created_at = Column(DateTime, default=utcnow)


class AuditEntry(Base):
    __tablename__ = "audit_entries"

    id = Column(String, primary_key=True)
    actor_type = Column(String, default="user")
    actor_name = Column(String)
    action = Column(String, nullable=False)
    entity_type = Column(String)
    entity_id = Column(String)
    patient_id = Column(String)
    before = Column(JSON, default=dict)
    after = Column(JSON, default=dict)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)


class CreditAccount(Base):
    __tablename__ = "credit_account"

    id = Column(String, primary_key=True)
    pack_size = Column(Integer, default=5000)
    balance = Column(Integer, default=5000)
    updated_at = Column(DateTime, default=utcnow)


class CreditEntry(Base):
    __tablename__ = "credit_ledger"

    id = Column(String, primary_key=True)
    operation = Column(String, nullable=False)
    units = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    feature = Column(String)
    mode = Column(String)
    llm_call_id = Column(String)
    patient_id = Column(String)
    actor = Column(String)
    created_at = Column(DateTime, default=utcnow)
