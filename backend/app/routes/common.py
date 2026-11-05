from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import (
    AuditEntry,
    Document,
    DocumentRequest,
    InvestigationRequest,
    Referral,
    Task,
    TimelineEvent,
)
from ..services.timeline import (
    add_audit,
    add_event,
    get_encounter,
    get_patient,
    get_state,
)

# --------------------------------------------------------------------------
# Request bodies
# --------------------------------------------------------------------------
class NoteGenerateRequest(BaseModel):
    feature: Literal["F1", "F2", "F3", "F4"]
    transcript: str = Field(min_length=10)
    title: str | None = None


class DraftPatchRequest(BaseModel):
    content: dict[str, Any]
    editor: str | None = None


class ApproveRequest(BaseModel):
    content: dict[str, Any] | None = None
    approved_by: str | None = None
    # A reason for approving past a warning (for example open safety alerts at discharge).
    override: dict[str, Any] | None = None


class RejectRequest(BaseModel):
    reason: str = Field(min_length=10)
    actor: str | None = None


class AcceptTasksRequest(BaseModel):
    indices: list[int]
    actor: str | None = None


class DismissRequest(BaseModel):
    reason: str = Field(min_length=10)
    actor: str | None = None


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=3)
    detail: str = ""
    priority: Literal["routine", "urgent", "critical"] = "routine"
    due_in_hours: int = 24
    owner: str | None = None
    category: Literal["general", "lab", "ct", "mri", "xray", "ultrasound", "ecg"] = "general"
    assignee_role: Literal["senior_doctor", "nurse"] | None = None


class TaskUpdateRequest(BaseModel):
    status: Literal["proposed", "accepted", "acknowledged", "in_progress", "completed", "cancelled"]
    actor: str | None = None


class TaskAssignRequest(BaseModel):
    assigned_to: str = ""
    actor: str | None = None


class TaskActionRequest(BaseModel):
    actor: str | None = None
    reason: str | None = None


class ReferralGenerateRequest(BaseModel):
    specialty: str | None = None
    urgency: str | None = None


class ReferralCompleteRequest(BaseModel):
    response_summary: str = ""
    actor: str | None = None


class ConsentRequest(BaseModel):
    consent_type: Literal["consultation_capture", "audio_recording", "treatment"] = "consultation_capture"
    granted: bool = True
    actor: str | None = None
    note: str = ""


class VerifyAllergyRequest(BaseModel):
    substance: str = Field(min_length=2)
    actor: str | None = None
    source_event_id: str | None = None


class ConfirmFieldRequest(BaseModel):
    index: int
    value: str | None = None
    actor: str | None = None


class DocumentRequestGenerateRequest(BaseModel):
    request_type: str | None = None


class MatchRequest(BaseModel):
    document_id: str


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _patient_encounter(db: Session, encounter_id: str | None = None):
    patient = get_patient(db)
    encounter = get_encounter(db, encounter_id)
    return patient, encounter


def _state(db: Session, encounter_id: str | None = None):
    patient, encounter = _patient_encounter(db, encounter_id)
    return patient, encounter, get_state(db, patient, encounter)


def _doc_dict(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "filename": document.filename,
        "mime": document.mime,
        "doc_type": document.doc_type,
        "ocr_status": document.ocr_status,
        "raw_text": document.raw_text,
        "extracted": document.extracted or {},
        "uploaded_by": document.uploaded_by,
        "uploaded_at": document.uploaded_at.isoformat(),
        "confirmed_by": document.confirmed_by,
        "confirmed_at": document.confirmed_at.isoformat() if document.confirmed_at else None,
        "image_url": f"/api/documents/{document.id}/image",
    }


def _task_dict(task: Task) -> dict[str, Any]:
    reference = utcnow()
    is_overdue = bool(
        task.due_at
        and task.due_at < reference
        and task.status not in {"completed", "cancelled"}
    )
    return {
        "id": task.id,
        "title": task.title,
        "detail": task.detail,
        "status": task.status,
        "priority": task.priority,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "owner": task.owner,
        "source_event_id": task.source_event_id,
        "accepted_from_draft_id": task.accepted_from_draft_id,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "assigned_to": task.assigned_to,
        "assigned_at": task.assigned_at.isoformat() if task.assigned_at else None,
        "acknowledged_at": task.acknowledged_at.isoformat() if task.acknowledged_at else None,
        "acknowledged_by": task.acknowledged_by,
        # The doctor completes on the assignee's behalf; the assignee is who the task is credited to.
        "completed_by": task.assigned_to if task.status == "completed" else None,
        "escalation_level": task.escalation_level or 0,
        "escalated_at": task.escalated_at.isoformat() if task.escalated_at else None,
        "escalation_reason": task.escalation_reason,
        "is_overdue": is_overdue,
        "category": task.category or "general",
        "assignee_role": task.assignee_role,
        "queue_rank": task.queue_rank or 0,
        "completion_event_id": task.completion_event_id,
    }


def _investigation_dict(request: InvestigationRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "request_type": request.request_type,
        "study": request.study,
        "indication": request.indication,
        "diagnosis": request.diagnosis,
        "allergies_to_verify": request.allergies_to_verify or [],
        "priority": request.priority,
        "instructions": request.instructions,
        "status": request.status,
        "draft_id": request.draft_id,
        "approved_by": request.approved_by,
        "created_at": request.created_at.isoformat() if request.created_at else None,
        "exported_at": request.exported_at.isoformat() if request.exported_at else None,
    }


def _referral_dict(referral: Referral) -> dict[str, Any]:
    return {
        "id": referral.id,
        "specialty": referral.specialty,
        "specialist": referral.specialist,
        "question": referral.question,
        "history": referral.history,
        "urgency": referral.urgency,
        "status": referral.status,
        "draft_id": referral.draft_id,
        "approved_by": referral.approved_by,
        "sent_at": referral.sent_at.isoformat() if referral.sent_at else None,
        "acknowledged_at": referral.acknowledged_at.isoformat() if referral.acknowledged_at else None,
        "completed_at": referral.completed_at.isoformat() if referral.completed_at else None,
        "response_summary": referral.response_summary,
        "consult_event_id": referral.consult_event_id,
        "created_at": referral.created_at.isoformat() if referral.created_at else None,
    }


def _request_dict(request: DocumentRequest) -> dict[str, Any]:
    overdue = bool(
        request.due_at
        and request.due_at < utcnow()
        and request.status in {"approved", "exported"}
    )
    return {
        "id": request.id,
        "request_type": request.request_type,
        "records_requested": request.records_requested or [],
        "recipient": request.recipient,
        "justification": request.justification,
        "due_at": request.due_at.isoformat() if request.due_at else None,
        "status": "overdue" if overdue else request.status,
        "matched_document_id": request.matched_document_id,
        "draft_id": request.draft_id,
        "created_at": request.created_at.isoformat(),
        "approved_by": request.approved_by,
    }


def _audit_dict(entry: AuditEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "actor_type": entry.actor_type,
        "actor_name": entry.actor_name,
        "action": entry.action,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "patient_id": entry.patient_id,
        "before": entry.before or {},
        "after": entry.after or {},
        "meta": entry.meta or {},
        "created_at": entry.created_at.isoformat(),
    }


def _document_to_labs(db: Session, document: Document, actor: str) -> list[TimelineEvent]:
    fields = (document.extracted or {}).get("fields", [])
    pending = [field for field in fields if float(field.get("confidence", 1)) < 0.8]
    if pending:
        raise ValueError(
            "Confirm low-confidence fields before committing: "
            + ", ".join(str(field.get("name")) for field in pending)
        )
    created = []
    for field in fields:
        value = field.get("value")
        flag = "unknown"
        reference = str(field.get("reference_range", ""))
        match = re.findall(r"\d+(?:\.\d+)?", reference)
        try:
            numeric = float(value)
            if len(match) >= 2:
                low, high = float(match[0]), float(match[1])
                if numeric < low:
                    flag = "low"
                elif numeric > high:
                    flag = "high"
                else:
                    flag = "normal"
        except (TypeError, ValueError):
            pass
        event = add_event(
            db,
            patient_id=document.patient_id,
            encounter_id=document.encounter_id,
            type="lab_result",
            title=f"{field.get('name')} — {value} {field.get('unit', '')}".strip(),
            body_text=(
                f"{field.get('name')}: {value} {field.get('unit', '')} "
                f"(reference {reference}); confirmed from {document.filename}."
            ),
            payload={
                "name": field.get("name"),
                "value": value,
                "unit": field.get("unit", ""),
                "reference_range": reference,
                "flag": flag,
                "review_status": "reviewed",
                "collected_at": field.get("collected_at", ""),
                "document_id": document.id,
                "confidence": 1.0,
            },
            source="F8",
            author_type="human",
            author_name=actor,
            document_id=document.id,
        )
        created.append(event)
    document.ocr_status = "confirmed"
    document.confirmed_by = actor
    document.confirmed_at = utcnow()
    add_audit(
        db,
        "document_confirmed",
        "document",
        document.id,
        document.patient_id,
        actor_name=actor,
        after={"labs_created": [event.id for event in created]},
    )
    for event in created:
        add_audit(
            db,
            "timeline_committed",
            "timeline_event",
            event.id,
            document.patient_id,
            after={"type": event.type, "title": event.title, "source": "F8"},
        )
    return created
