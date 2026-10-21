from __future__ import annotations

import re
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from . import clock
from .config import settings
from .db import get_db, utcnow
from .modules import module_registry
from .models import (
    Alert,
    AuditEntry,
    ClaimReview,
    Document,
    DocumentRequest,
    Draft,
    Encounter,
    InvestigationRequest,
    LLMCall,
    Patient,
    Referral,
    Task,
    TimelineEvent,
)
from .schemas import FEATURE_MODELS
from .seed import reset_demo
from .services.context import build_context, create_transcript_event
from .services.drafts import (
    accept_tasks,
    approve_draft,
    create_draft,
    draft_to_dict,
    reject_draft,
    update_draft,
)
from .services.llm import DraftGenerationError, generate_draft
from .services.ocr import new_document, run_ocr, sample_svg
from .services.revenue import claim_pack_html, claim_prep, leakage, reconciliation
from .services.rules import evaluate_rules
from .services.timeline import (
    add_audit,
    add_event,
    event_to_dict,
    get_encounter,
    get_event,
    get_patient,
    get_state,
    list_events,
    new_id,
)

router = APIRouter(prefix="/api")


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
    patient = get_patient(db, "pat_ravi")
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
        "escalation_level": task.escalation_level or 0,
        "escalated_at": task.escalated_at.isoformat() if task.escalated_at else None,
        "escalation_reason": task.escalation_reason,
        "is_overdue": is_overdue,
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


# --------------------------------------------------------------------------
# Meta and patient
# --------------------------------------------------------------------------
@router.get("/meta")
def meta(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    return {
        "product": "MediBytes ARD",
        "patient": state["patient"],
        "encounter": state["encounter"],
        "demo_now": clock.now().replace(microsecond=0).isoformat(),
        "server_now": clock.real_utcnow().replace(microsecond=0).isoformat(),
        "llm_mode": settings.effective_llm_mode,
        "model": settings.openai_model,
        "live_available": bool(settings.openai_api_key),
        "demo_user": settings.demo_user,
        "demo_role": settings.demo_role,
        "features": list(FEATURE_MODELS.keys()),
        "disclaimer": "Synthetic demo data. Not for clinical use.",
    }


@router.get("/modules")
def modules():
    return module_registry()


@router.get("/patients/{patient_id}")
def patient_detail(patient_id: str, db: Session = Depends(get_db)):
    patient = get_patient(db, patient_id)
    encounter = get_encounter(db)
    return {
        "patient": {
            "id": patient.id,
            "mrn": patient.mrn,
            "name": patient.name,
            "age": patient.age,
            "sex": patient.sex,
            "allergies": patient.allergies,
            "problems": patient.problems,
        },
        "state": get_state(db, patient, encounter),
    }


@router.get("/patients/{patient_id}/state")
def patient_state(patient_id: str, db: Session = Depends(get_db)):
    patient = get_patient(db, patient_id)
    encounter = get_encounter(db)
    return get_state(db, patient, encounter)


@router.get("/patients/{patient_id}/consents")
def patient_consents(patient_id: str, encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient = get_patient(db, patient_id)
    stmt = select(TimelineEvent).where(
        TimelineEvent.patient_id == patient.id,
        TimelineEvent.type == "consent",
    )
    if encounter_id:
        stmt = stmt.where(TimelineEvent.encounter_id == encounter_id)
    rows = list(db.scalars(stmt.order_by(TimelineEvent.occurred_at.desc())))
    return {
        "consents": [
            {
                "id": event.id,
                "consent_type": (event.payload or {}).get("consent_type"),
                "granted": (event.payload or {}).get("granted"),
                "actor": event.author_name,
                "note": (event.payload or {}).get("note", ""),
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in rows
        ]
    }


@router.post("/patients/{patient_id}/consents")
def record_consent(patient_id: str, body: ConsentRequest, encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient = get_patient(db, patient_id)
    encounter = get_encounter(db, encounter_id)
    actor = body.actor or settings.demo_user
    event = add_event(
        db,
        patient_id=patient.id,
        encounter_id=encounter.id,
        type="consent",
        subtype=body.consent_type,
        title=f"Consent — {body.consent_type.replace('_', ' ')}",
        body_text=(
            f"{'Granted' if body.granted else 'Declined'} by patient for "
            f"{body.consent_type.replace('_', ' ')}. {body.note}".strip()
        ),
        payload={
            "consent_type": body.consent_type,
            "granted": body.granted,
            "note": body.note,
            "captured_by": actor,
        },
        source="consent",
        author_type="human",
        author_name=actor,
        status="approved",
        approved_by=actor,
    )
    add_audit(
        db,
        "consent_recorded",
        "timeline_event",
        event.id,
        patient.id,
        actor_name=actor,
        after={"consent_type": body.consent_type, "granted": body.granted},
    )
    db.commit()
    return {
        "id": event.id,
        "consent_type": body.consent_type,
        "granted": body.granted,
        "occurred_at": event.occurred_at.isoformat(),
    }


@router.get("/patients/{patient_id}/timeline")
def patient_timeline(
    patient_id: str,
    encounter_id: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    get_patient(db, patient_id)
    events = list_events(db, patient_id, encounter_id, approved_only=True, limit=limit)
    return {"events": [event_to_dict(event) for event in events], "count": len(events)}


@router.get("/events/{event_id}")
def event_detail(event_id: str, db: Session = Depends(get_db)):
    return event_to_dict(get_event(db, event_id))


# --------------------------------------------------------------------------
# Drafts and approvals
# --------------------------------------------------------------------------
@router.get("/drafts")
def drafts(
    feature: str | None = None,
    encounter_id: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(Draft).order_by(Draft.created_at.desc()).limit(limit)
    if feature:
        stmt = stmt.where(Draft.feature == feature)
    if encounter_id:
        stmt = stmt.where(Draft.encounter_id == encounter_id)
    rows = list(db.scalars(stmt))
    return {"drafts": [draft_to_dict(draft) for draft in rows]}


@router.get("/drafts/{draft_id}")
def draft_detail(draft_id: str, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    return draft_to_dict(draft)


@router.patch("/drafts/{draft_id}")
def draft_patch(draft_id: str, body: DraftPatchRequest, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    update_draft(db, draft, body.content, body.editor)
    db.commit()
    return draft_to_dict(draft)


@router.post("/drafts/{draft_id}/verify-allergy")
def draft_verify_allergy(draft_id: str, body: VerifyAllergyRequest, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    if draft.feature != "F2":
        raise HTTPException(400, "Allergy verification applies to the F2 admission assessment")
    if draft.status in {"approved", "rejected"}:
        raise HTTPException(400, "This draft is no longer open for verification")
    content = dict(draft.content or {})
    allergies = [dict(item) for item in content.get("allergies_to_verify", [])]
    match = next(
        (item for item in allergies if str(item.get("substance", "")).lower() == body.substance.lower()),
        None,
    )
    if not match:
        raise HTTPException(404, "Allergy not found in this draft")
    actor = body.actor or settings.demo_user
    match["verified"] = True
    match["verified_by"] = actor
    match["verified_at"] = utcnow().isoformat()
    if body.source_event_id:
        match["source_event_id"] = body.source_event_id
    content["allergies_to_verify"] = allergies
    draft.content = content
    draft.status = "human_edited"
    draft.edited_by = actor
    draft.updated_at = utcnow()
    flag_modified(draft, "content")
    add_audit(
        db,
        "allergy_verified",
        "draft",
        draft.id,
        draft.patient_id,
        actor_name=actor,
        after={
            "substance": body.substance,
            "source_event_id": match.get("source_event_id"),
        },
    )
    db.commit()
    return draft_to_dict(draft)


@router.post("/drafts/{draft_id}/approve")
def draft_approve(draft_id: str, body: ApproveRequest, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    event = approve_draft(db, draft, body.content, body.approved_by)
    patient, encounter, state = _state(db, draft.encounter_id)
    created_alerts = evaluate_rules(db, patient, encounter, state)
    db.commit()
    return {
        "draft": draft_to_dict(draft),
        "event": event_to_dict(event) if event else None,
        "new_alerts": [{"id": alert.id, "rule_id": alert.rule_id, "title": alert.title} for alert in created_alerts],
    }


@router.post("/drafts/{draft_id}/reject")
def draft_reject(draft_id: str, body: RejectRequest, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    reject_draft(db, draft, body.reason, body.actor)
    db.commit()
    return draft_to_dict(draft)


@router.post("/drafts/{draft_id}/accept-tasks")
def draft_accept_tasks(draft_id: str, body: AcceptTasksRequest, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    tasks = accept_tasks(db, draft, body.indices, body.actor)
    db.commit()
    return {"tasks": [_task_dict(task) for task in tasks]}


# --------------------------------------------------------------------------
# Notes (F1, F2, F3, F4)
# --------------------------------------------------------------------------
@router.post("/notes/transcribe")
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


@router.post("/notes/generate")
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
        },
    }


@router.get("/notes/latest")
def latest_notes(feature: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Draft).order_by(Draft.created_at.desc()).limit(10)
    if feature:
        stmt = stmt.where(Draft.feature == feature)
    rows = list(db.scalars(stmt))
    return {"drafts": [draft_to_dict(draft) for draft in rows]}


# --------------------------------------------------------------------------
# ICU flow sheets (F7) and investigations support
# --------------------------------------------------------------------------
def _icu_encounter_id(db: Session, encounter_id: str | None) -> str | None:
    if encounter_id and db.get(Encounter, encounter_id):
        return encounter_id
    icu = db.get(Encounter, "enc_icu_1")
    return icu.id if icu else None


@router.get("/icu/flow-sheet")
def icu_flow_sheet(encounter_id: str | None = None, db: Session = Depends(get_db)):
    resolved = _icu_encounter_id(db, encounter_id)
    _, _, state = _state(db, resolved)
    return {
        "encounter": state["encounter"],
        "shift_window": state.get("icu_shift_window", {}),
        "entries": state.get("icu_entries", []),
    }


@router.post("/icu/flow-sheet/generate")
def generate_icu_flow_sheet(encounter_id: str | None = None, db: Session = Depends(get_db)):
    resolved = _icu_encounter_id(db, encounter_id)
    patient, encounter, state = _state(db, resolved)
    context = build_context(db, patient, encounter, state, "F7")
    content, llm_call = generate_draft(db, "F7", context)
    draft = create_draft(db, feature="F7", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode, "latency_ms": llm_call.latency_ms}}


@router.get("/investigations")
def investigations(encounter_id: str | None = None, db: Session = Depends(get_db)):
    _, _, state = _state(db, encounter_id)
    return {
        "labs": state["latest_labs"],
        "unreviewed": state["unreviewed_labs"],
        "reviewed_count": len(state["latest_labs"]) - len(state["unreviewed_labs"]),
    }


@router.post("/labs/{event_id}/review")
def review_lab(event_id: str, db: Session = Depends(get_db)):
    event = get_event(db, event_id)
    if event.type != "lab_result":
        raise HTTPException(400, "Event is not a laboratory result")
    before = dict(event.payload or {})
    event.payload = {**before, "review_status": "reviewed"}
    flag_modified(event, "payload")
    add_audit(
        db,
        "lab_reviewed",
        "timeline_event",
        event.id,
        event.patient_id,
        before=before,
        after=event.payload,
    )
    alerts = list(
        db.scalars(
            select(Alert).where(
                Alert.status == "open",
                Alert.rule_id == "R3",
                Alert.patient_id == event.patient_id,
            )
        )
    )
    for alert in alerts:
        if event.id in (alert.evidence_event_ids or []):
            alert.status = "acknowledged"
            alert.acknowledged_by = settings.demo_user
            alert.resolved_at = utcnow()
            add_audit(
                db,
                "alert_acknowledged",
                "alert",
                alert.id,
                event.patient_id,
                after={"reason": "Result reviewed", "lab_event_id": event.id},
            )
    db.commit()
    return {"event": event_to_dict(event)}


# --------------------------------------------------------------------------
# Safety
# --------------------------------------------------------------------------
@router.get("/alerts")
def alerts(encounter_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Alert).order_by(Alert.created_at.desc())
    if encounter_id:
        stmt = stmt.where(Alert.encounter_id == encounter_id)
    else:
        _, current, _ = _state(db)
        stmt = stmt.where(Alert.encounter_id == current.id)
    rows = list(db.scalars(stmt))
    return {
        "alerts": [
            {
                "id": alert.id,
                "rule_id": alert.rule_id,
                "severity": alert.severity,
                "status": alert.status,
                "title": alert.title,
                "explanation": alert.explanation,
                "recommended_action": alert.recommended_action,
                "evidence_event_ids": alert.evidence_event_ids or [],
                "acknowledged_by": alert.acknowledged_by,
                "dismissed_by": alert.dismissed_by,
                "dismissal_reason": alert.dismissal_reason,
                "created_at": alert.created_at.isoformat(),
                "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
            }
            for alert in rows
        ],
        "open_count": sum(1 for alert in rows if alert.status == "open"),
    }


@router.post("/alerts/evaluate")
def evaluate_alerts(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    created = evaluate_rules(db, patient, encounter, state)
    db.commit()
    return {"created": [{"id": alert.id, "rule_id": alert.rule_id, "title": alert.title} for alert in created]}


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status = "acknowledged"
    alert.acknowledged_by = settings.demo_user
    alert.resolved_at = utcnow()
    add_audit(
        db,
        "alert_acknowledged",
        "alert",
        alert.id,
        alert.patient_id,
        after={"rule_id": alert.rule_id, "status": alert.status},
    )
    db.commit()
    return {"id": alert.id, "status": alert.status}


@router.post("/alerts/{alert_id}/dismiss")
def dismiss_alert(alert_id: str, body: DismissRequest, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status = "dismissed"
    alert.dismissed_by = body.actor or settings.demo_user
    alert.dismissal_reason = body.reason.strip()
    alert.resolved_at = utcnow()
    add_audit(
        db,
        "alert_dismissed",
        "alert",
        alert.id,
        alert.patient_id,
        actor_name=alert.dismissed_by,
        after={"rule_id": alert.rule_id, "reason": alert.dismissal_reason},
    )
    db.commit()
    return {"id": alert.id, "status": alert.status, "reason": alert.dismissal_reason}


@router.get("/medications")
def medications(encounter_id: str | None = None, db: Session = Depends(get_db)):
    _, _, state = _state(db, encounter_id)
    return {
        "home_medications": state["home_meds"],
        "current_medications": state["active_meds"],
    }


@router.get("/medications/reconciliation")
def medication_reconciliation(encounter_id: str | None = None, db: Session = Depends(get_db)):
    _, _, state = _state(db, encounter_id)
    return reconciliation(state)


@router.post("/medications/reconciliation/generate")
def generate_reconciliation(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    recon = reconciliation(state)
    context = build_context(db, patient, encounter, state, "F6", extra={"reconciliation": recon})
    content, llm_call = generate_draft(db, "F6", context)
    draft = create_draft(db, feature="F6", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "reconciliation": recon, "llm": {"mode": llm_call.mode}}


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------
@router.get("/tasks")
def tasks_list(
    encounter_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Task).order_by(Task.created_at.desc())
    if encounter_id:
        stmt = stmt.where(Task.encounter_id == encounter_id)
    else:
        # The single-patient demo board shows the current encounter only. The
        # hospital aggregate reads all tasks directly for F14.
        _, current, _ = _state(db)
        stmt = stmt.where(Task.encounter_id == current.id)
    if status:
        stmt = stmt.where(Task.status == status)
    rows = list(db.scalars(stmt))
    return {"tasks": [_task_dict(task) for task in rows]}


@router.post("/tasks")
def task_create(body: TaskCreateRequest, db: Session = Depends(get_db)):
    patient, encounter, _ = _state(db)
    task = Task(
        id=new_id("tsk"),
        patient_id=patient.id,
        encounter_id=encounter.id,
        title=body.title.strip(),
        detail=body.detail.strip(),
        status="accepted",
        priority=body.priority,
        due_at=utcnow() + timedelta(hours=body.due_in_hours),
        owner=body.owner or settings.demo_user,
        assigned_to=body.owner or settings.demo_user,
        assigned_at=utcnow(),
        assigned_by=settings.demo_user,
        created_by=settings.demo_user,
        created_at=utcnow(),
    )
    db.add(task)
    add_audit(
        db,
        "task_created",
        "task",
        task.id,
        patient.id,
        after={"title": task.title, "priority": task.priority, "due_at": task.due_at.isoformat()},
    )
    db.commit()
    return _task_dict(task)


@router.post("/tasks/{task_id}/assign")
def task_assign(task_id: str, body: TaskAssignRequest, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    previous = task.owner
    assigned = body.assigned_to.strip() or None
    task.assigned_to = assigned
    task.owner = assigned
    task.assigned_at = utcnow() if assigned else None
    task.assigned_by = (body.actor or settings.demo_user) if assigned else None
    add_audit(
        db,
        "task_assigned" if assigned else "task_unassigned",
        "task",
        task.id,
        task.patient_id,
        actor_name=body.actor or settings.demo_user,
        before={"owner": previous},
        after={"assigned_to": assigned},
    )
    db.commit()
    return _task_dict(task)


@router.post("/tasks/{task_id}/acknowledge")
def task_acknowledge(task_id: str, body: TaskActionRequest, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if not task.assigned_to:
        raise HTTPException(400, "Assign the task before it can be acknowledged")
    if task.status not in {"proposed", "accepted", "in_progress"}:
        raise HTTPException(400, f"Task is {task.status} and cannot be acknowledged")
    task.status = "acknowledged"
    task.acknowledged_at = utcnow()
    task.acknowledged_by = body.actor or task.assigned_to or settings.demo_user
    add_audit(
        db,
        "task_acknowledged",
        "task",
        task.id,
        task.patient_id,
        actor_name=task.acknowledged_by,
        after={"status": task.status, "title": task.title},
    )
    db.commit()
    return _task_dict(task)


@router.post("/tasks/{task_id}/escalate")
def task_escalate(task_id: str, body: TaskActionRequest, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    task.escalation_level = min((task.escalation_level or 0) + 1, 2)
    task.escalated_at = utcnow()
    task.escalation_reason = body.reason or "Manual escalation from the task board"
    add_audit(
        db,
        "task_escalated",
        "task",
        task.id,
        task.patient_id,
        actor_name=body.actor or settings.demo_user,
        after={
            "escalation_level": task.escalation_level,
            "escalation_reason": task.escalation_reason,
        },
    )
    db.commit()
    return _task_dict(task)


@router.post("/tasks/escalations/run")
def run_task_escalations(body: TaskActionRequest, db: Session = Depends(get_db)):
    now = utcnow()
    tasks = list(
        db.scalars(
            select(Task).where(Task.status.notin_(["completed", "cancelled"]))
        )
    )
    escalated = []
    for task in tasks:
        if not task.due_at:
            continue
        overdue_hours = (now - task.due_at).total_seconds() / 3600
        level = 2 if overdue_hours >= 8 else 1 if overdue_hours >= 2 else 0
        if level <= (task.escalation_level or 0):
            continue
        task.escalation_level = level
        task.escalated_at = now
        task.escalation_reason = (
            f"Automatically escalated after {overdue_hours:.1f} hours overdue"
        )
        escalated.append(task)
        add_audit(
            db,
            "task_escalated",
            "task",
            task.id,
            task.patient_id,
            actor_type="system",
            actor_name="Escalation engine",
            after={
                "escalation_level": level,
                "overdue_hours": round(overdue_hours, 1),
                "owner": task.owner,
            },
        )
    db.commit()
    return {"escalated": [_task_dict(task) for task in escalated], "count": len(escalated)}


@router.patch("/tasks/{task_id}")
def task_update(task_id: str, body: TaskUpdateRequest, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    before = {"status": task.status}
    task.status = body.status
    if body.status == "completed":
        task.completed_at = utcnow()
    if body.status == "acknowledged":
        task.acknowledged_at = utcnow()
        task.acknowledged_by = body.actor or settings.demo_user
    add_audit(
        db,
        "task_status_changed",
        "task",
        task.id,
        task.patient_id,
        actor_name=body.actor or settings.demo_user,
        before=before,
        after={"status": task.status, "title": task.title},
    )
    db.commit()
    return _task_dict(task)


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
@router.get("/documents")
def documents_list(encounter_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Document).order_by(Document.uploaded_at.desc())
    if encounter_id:
        stmt = stmt.where(Document.encounter_id == encounter_id)
    rows = list(db.scalars(stmt))
    return {"documents": [_doc_dict(document) for document in rows]}


@router.post("/documents/upload")
async def document_upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    patient, encounter, _ = _state(db)
    contents = await file.read()
    if len(contents) > 12 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 12 MB)")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", file.filename or "upload.png")
    stored = settings.uploads_dir / f"{uuid.uuid4().hex[:10]}_{safe}"
    stored.write_bytes(contents)
    document = new_document(
        db,
        patient_id=patient.id,
        encounter_id=encounter.id,
        filename=safe,
        path=str(stored),
        mime=file.content_type or "image/png",
        image_kind="file",
        doc_type="lab_report",
    )
    run_ocr(db, document)
    db.commit()
    return _doc_dict(document)


@router.get("/documents/{document_id}")
def document_detail(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    return _doc_dict(document)


@router.get("/documents/{document_id}/image")
def document_image(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    if document.image_kind == "svg":
        return Response(
            sample_svg("Ravi Menon", "MB-1001"),
            media_type="image/svg+xml",
            headers={"Cache-Control": "no-store"},
        )
    path = Path(document.path or "")
    if not path.exists():
        raise HTTPException(404, "Stored image missing")
    return FileResponse(path, media_type=document.mime or "application/octet-stream")


@router.post("/documents/{document_id}/confirm-field")
def document_confirm_field(document_id: str, body: ConfirmFieldRequest, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    extracted = document.extracted or {}
    fields = extracted.get("fields", [])
    if body.index < 0 or body.index >= len(fields):
        raise HTTPException(400, "Field index out of range")
    if body.value is not None:
        fields[body.index]["value"] = body.value
    fields[body.index]["confidence"] = 1.0
    fields[body.index]["confirmed"] = True
    document.extracted = {**extracted, "fields": [dict(field) for field in fields]}
    flag_modified(document, "extracted")
    if all(float(field.get("confidence", 1)) >= 0.8 for field in fields):
        document.ocr_status = "reviewed"
    add_audit(
        db,
        "document_field_confirmed",
        "document",
        document.id,
        document.patient_id,
        actor_name=body.actor or settings.demo_user,
        after={"field": fields[body.index].get("name"), "value": fields[body.index].get("value")},
    )
    db.commit()
    return _doc_dict(document)


@router.post("/documents/{document_id}/commit")
def document_commit(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    labs = _document_to_labs(db, document, settings.demo_user)
    patient, encounter, state = _state(db, document.encounter_id)
    created_alerts = evaluate_rules(db, patient, encounter, state)
    db.commit()
    return {
        "document": _doc_dict(document),
        "labs": [event_to_dict(event) for event in labs],
        "new_alerts": [{"id": alert.id, "rule_id": alert.rule_id, "title": alert.title} for alert in created_alerts],
    }


# --------------------------------------------------------------------------
# Investigation and radiology requests (F10), smart referrals (F11)
# --------------------------------------------------------------------------
@router.get("/investigation-requests")
def investigation_requests(encounter_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(InvestigationRequest).order_by(InvestigationRequest.created_at.desc())
    if encounter_id:
        stmt = stmt.where(InvestigationRequest.encounter_id == encounter_id)
    else:
        _, current, _ = _state(db)
        stmt = stmt.where(InvestigationRequest.encounter_id == current.id)
    rows = list(db.scalars(stmt))
    return {"requests": [_investigation_dict(request) for request in rows]}


@router.post("/investigation-requests/generate")
def generate_investigation_request(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db, encounter_id)
    context = build_context(db, patient, encounter, state, "F10")
    content, llm_call = generate_draft(db, "F10", context)
    draft = create_draft(db, feature="F10", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode, "latency_ms": llm_call.latency_ms}}


@router.post("/investigation-requests/{request_id}/export")
def export_investigation_request(request_id: str, db: Session = Depends(get_db)):
    request = db.get(InvestigationRequest, request_id)
    if not request:
        raise HTTPException(404, "Investigation request not found")
    request.status = "exported"
    request.exported_at = utcnow()
    add_audit(
        db,
        "investigation_request_exported",
        "investigation_request",
        request.id,
        request.patient_id,
        after={"status": request.status, "study": request.study},
        meta={"note": "Demo export only; no laboratory or radiology transmission exists"},
    )
    db.commit()
    return _investigation_dict(request)


@router.get("/referrals")
def referrals(encounter_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Referral).order_by(Referral.created_at.desc())
    if encounter_id:
        stmt = stmt.where(Referral.encounter_id == encounter_id)
    else:
        _, current, _ = _state(db)
        stmt = stmt.where(Referral.encounter_id == current.id)
    rows = list(db.scalars(stmt))
    return {"referrals": [_referral_dict(referral) for referral in rows]}


@router.post("/referrals/generate")
def generate_referral(body: ReferralGenerateRequest | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    context = build_context(db, patient, encounter, state, "F11")
    content, llm_call = generate_draft(db, "F11", context)
    if body and body.specialty:
        content["specialty"] = body.specialty
    if body and body.urgency:
        content["urgency"] = body.urgency
    draft = create_draft(db, feature="F11", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode, "latency_ms": llm_call.latency_ms}}


@router.post("/referrals/{referral_id}/acknowledge")
def acknowledge_referral(referral_id: str, body: TaskActionRequest, db: Session = Depends(get_db)):
    referral = db.get(Referral, referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")
    if referral.status != "sent":
        raise HTTPException(400, f"Referral is {referral.status}; only a sent referral can be acknowledged")
    referral.status = "acknowledged"
    referral.acknowledged_at = utcnow()
    update_event = add_event(
        db,
        patient_id=referral.patient_id,
        encounter_id=referral.encounter_id,
        type="referral_update",
        subtype=referral.specialty,
        title=f"Referral acknowledged — {referral.specialty}",
        body_text="The specialist service acknowledged the referral. No external transmission occurred in this demo.",
        payload={"referral_id": referral.id, "status": "acknowledged"},
        source="referral",
        author_type="human",
        author_name=body.actor or settings.demo_user,
    )
    add_audit(
        db,
        "referral_acknowledged",
        "referral",
        referral.id,
        referral.patient_id,
        actor_name=body.actor or settings.demo_user,
        after={"status": referral.status, "specialty": referral.specialty},
    )
    db.commit()
    return _referral_dict(referral)


@router.post("/referrals/{referral_id}/complete")
def complete_referral(referral_id: str, body: ReferralCompleteRequest, db: Session = Depends(get_db)):
    referral = db.get(Referral, referral_id)
    if not referral:
        raise HTTPException(404, "Referral not found")
    if referral.status not in {"sent", "acknowledged"}:
        raise HTTPException(400, f"Referral is {referral.status}; it cannot be completed")
    referral.status = "completed"
    referral.completed_at = utcnow()
    referral.response_summary = body.response_summary.strip()
    consult = add_event(
        db,
        patient_id=referral.patient_id,
        encounter_id=referral.encounter_id,
        type="referral_consult",
        subtype=referral.specialty,
        title=f"Specialist response — {referral.specialty}",
        body_text=referral.response_summary or "Referral marked complete without a written response.",
        payload={
            "referral_id": referral.id,
            "status": "completed",
            "response_summary": referral.response_summary,
        },
        source="referral",
        author_type="human",
        author_name=body.actor or settings.demo_user,
    )
    referral.consult_event_id = consult.id
    add_audit(
        db,
        "referral_completed",
        "referral",
        referral.id,
        referral.patient_id,
        actor_name=body.actor or settings.demo_user,
        after={"status": referral.status, "response_summary": referral.response_summary},
    )
    db.commit()
    return _referral_dict(referral)


# --------------------------------------------------------------------------
# Document requests (supporting follow-up, not F10)
# --------------------------------------------------------------------------
@router.get("/document-requests")
def document_requests(encounter_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(DocumentRequest).order_by(DocumentRequest.created_at.desc())
    if encounter_id:
        stmt = stmt.where(DocumentRequest.encounter_id == encounter_id)
    rows = list(db.scalars(stmt))
    return {"requests": [_request_dict(request) for request in rows]}


@router.post("/document-requests/generate")
def generate_document_request(body: DocumentRequestGenerateRequest | None = None, db: Session = Depends(get_db)):
    """Supporting follow-up request for missing records or pre-authorization.

    This is deliberately separate from F10, which is the investigation/radiology
    requisition workflow. No external transmission is performed.
    """
    patient, encounter, state = _state(db)
    prep = claim_prep(db, patient, encounter, state)
    records = [item["label"] for item in prep["missing_documents"]] or ["Signed discharge summary"]
    request = DocumentRequest(
        id=new_id("req"),
        patient_id=patient.id,
        encounter_id=encounter.id,
        request_type=(body.request_type if body and body.request_type else "pre_auth"),
        records_requested=records,
        recipient="Star Health — Provider Desk",
        justification="Required before the claim pack can enter clinical review. Demo only; no transmission.",
        due_at=utcnow() + timedelta(days=3),
        status="approved",
        created_at=utcnow(),
        approved_by=settings.demo_user,
    )
    db.add(request)
    add_audit(
        db,
        "document_request_created",
        "document_request",
        request.id,
        patient.id,
        after={"records": records, "recipient": request.recipient},
        meta={"note": "Supporting follow-up only; no external transmission"},
    )
    db.commit()
    return {"request": _request_dict(request), "missing_documents": prep["missing_documents"]}


@router.post("/document-requests/{request_id}/export")
def export_document_request(request_id: str, db: Session = Depends(get_db)):
    request = db.get(DocumentRequest, request_id)
    if not request:
        raise HTTPException(404, "Request not found")
    request.status = "exported"
    add_audit(
        db,
        "document_request_exported",
        "document_request",
        request.id,
        request.patient_id,
        after={"status": request.status, "recipient": request.recipient},
        meta={"note": "Demo export only; no transmission exists"},
    )
    db.commit()
    return _request_dict(request)


@router.post("/document-requests/{request_id}/match")
def match_document_request(request_id: str, body: MatchRequest, db: Session = Depends(get_db)):
    request = db.get(DocumentRequest, request_id)
    document = db.get(Document, body.document_id)
    if not request or not document:
        raise HTTPException(404, "Request or document not found")
    request.status = "matched"
    request.matched_document_id = document.id
    add_audit(
        db,
        "document_request_matched",
        "document_request",
        request.id,
        request.patient_id,
        after={"document_id": document.id, "status": request.status},
    )
    db.commit()
    return _request_dict(request)


# --------------------------------------------------------------------------
# Discharge (F9)
# --------------------------------------------------------------------------
@router.get("/discharge/readiness")
def discharge_readiness(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db, encounter_id)
    events = list_events(db, patient.id, encounter.id, approved_only=True, limit=1000)
    types = {event.type for event in events}
    required = [
        ("consult_note", "Consultation note", "F1"),
        ("admission_note", "Admission assessment", "F2"),
        ("round_note", "Round handover", "F3"),
        ("lab_result", "Laboratory results", "Labs"),
        ("procedure", "Procedures documented", "Care"),
    ]
    items = [
        {
            "key": key,
            "label": label,
            "present": key in types,
            "source": source,
        }
        for key, label, source in required
    ]
    return {
        "items": items,
        "ready": all(item["present"] for item in items),
        "already_signed": state["discharge_signed"],
        "encounter_status": state["encounter"]["status"],
    }


@router.post("/discharge/generate")
def generate_discharge(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    context = build_context(db, patient, encounter, state, "F9")
    content, llm_call = generate_draft(db, "F9", context)
    draft = create_draft(db, feature="F9", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode, "latency_ms": llm_call.latency_ms}}


@router.get("/discharge/{draft_id}/print")
def discharge_print(draft_id: str, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    content = draft.content or {}
    sections = content.get("sections", [])
    body = "".join(
        f"<h2>{section.get('heading', '')}</h2>"
        + "".join(f"<p>{paragraph.get('text', '')}</p>" for paragraph in section.get("paragraphs", []))
        for section in sections
    )
    meds = "".join(
        f"<tr><td>{med.get('drug','')}</td><td>{med.get('dose','')}</td>"
        f"<td>{med.get('route','')}</td><td>{med.get('frequency','')}</td>"
        f"<td>{med.get('safety_note','') or 'clear'}</td></tr>"
        for med in content.get("medications", [])
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Discharge summary</title>
    <style>body{{font-family:Arial;margin:40px;color:#16181d}}h1{{font-size:22px}}
    h2{{font-size:15px;margin-top:24px}}p{{font-size:13px;line-height:1.6}}
    table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e3e6eb;padding:6px;font-size:13px;text-align:left}}
    .meta{{color:#6b7280;font-size:12px}}</style></head><body>
    <h1>Discharge summary</h1>
    <div class="meta">Ravi Menon · MB-1001 · Synthetic demo data</div>
    {body}
    <h2>Discharge medications</h2>
    <table><thead><tr><th>Drug</th><th>Dose</th><th>Route</th><th>Frequency</th><th>Safety</th></tr></thead>
    <tbody>{meds}</tbody></table>
    <p class="meta">Demo output. Not a clinical document.</p>
    </body></html>"""
    return HTMLResponse(html)


# --------------------------------------------------------------------------
# Revenue (F12, F13)
# --------------------------------------------------------------------------
@router.get("/revenue/claim-prep")
def revenue_claim_prep(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db, encounter_id)
    prep = claim_prep(db, patient, encounter, state)
    reviews = list(
        db.scalars(
            select(ClaimReview)
            .where(ClaimReview.encounter_id == encounter.id)
            .order_by(ClaimReview.created_at.desc())
        )
    )
    return {
        **prep,
        "reviews": [
            {
                "id": review.id,
                "status": review.status,
                "prepared_at": review.prepared_at.isoformat() if review.prepared_at else None,
                "reviewed_by": review.reviewed_by,
            }
            for review in reviews
        ],
    }


@router.post("/revenue/claim-prep/prepare")
def prepare_claim(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    prep = claim_prep(db, patient, encounter, state)
    review = ClaimReview(
        id=new_id("clm"),
        patient_id=patient.id,
        encounter_id=encounter.id,
        status=prep["status"],
        prepared_at=utcnow(),
        created_at=utcnow(),
    )
    db.add(review)
    add_audit(
        db,
        "claim_pack_prepared",
        "claim_review",
        review.id,
        patient.id,
        after={
            "status": review.status,
            "missing_documents": [item["label"] for item in prep["missing_documents"]],
            "unbilled": [item["procedure"] for item in prep["unbilled_procedures"]],
            "underbilled": [item["description"] for item in prep.get("underbilled_items", [])],
            "contradictions": [item["title"] for item in prep.get("contradictions", [])],
            "tpa_review": prep.get("tpa_review", {}),
            "total_amount": prep["total_amount"],
            "expected_total_amount": prep.get("expected_total_amount", prep["total_amount"]),
        },
        meta={"note": "Review queue only; no submission"},
    )
    db.commit()
    return {"review": {"id": review.id, "status": review.status}, "prep": prep}


@router.get("/revenue/claim-prep/pack.html")
def claim_pack(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db, encounter_id)
    prep = claim_prep(db, patient, encounter, state)
    return HTMLResponse(claim_pack_html(patient, encounter, prep))


@router.post("/revenue/claim-prep/explain")
def explain_claim(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    prep = claim_prep(db, patient, encounter, state)
    leak = leakage(db, patient, encounter, state)
    context = build_context(
        db,
        patient,
        encounter,
        state,
        "F12",
        extra={"revenue": {**prep, **leak}},
    )
    content, llm_call = generate_draft(db, "F12", context)
    draft = create_draft(db, feature="F12", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode}}


@router.get("/revenue/leakage")
def revenue_leakage(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db, encounter_id)
    return leakage(db, patient, encounter, state)


@router.post("/revenue/leakage/explain")
def explain_leakage(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    leak = leakage(db, patient, encounter, state)
    context = build_context(db, patient, encounter, state, "F13", extra={"revenue": leak})
    content, llm_call = generate_draft(db, "F13", context)
    draft = create_draft(db, feature="F13", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode}}


# --------------------------------------------------------------------------
# Dashboard and audit
# --------------------------------------------------------------------------
@router.get("/hospital/dashboard")
def hospital_dashboard(db: Session = Depends(get_db)):
    """Hospital-scoped operational queue for F14.

    This is deliberately a queue view, not a clinical decision surface. Every
    row is a real database record; the counts come from the demo clock.
    """
    patients = list(db.scalars(select(Patient).order_by(Patient.name)))
    encounters = list(db.scalars(select(Encounter).order_by(Encounter.admitted_at.desc())))
    tasks = list(db.scalars(select(Task)))
    alerts = list(db.scalars(select(Alert)))
    drafts = list(db.scalars(select(Draft)))
    documents = list(db.scalars(select(Document)))
    referrals = list(db.scalars(select(Referral)))
    investigations = list(db.scalars(select(InvestigationRequest)))
    now = utcnow()

    def latest_encounter(patient_id: str) -> Encounter | None:
        patient_encounters = [item for item in encounters if item.patient_id == patient_id]
        active = next((item for item in patient_encounters if item.status == "active"), None)
        if active:
            return active
        # After discharge, keep the episode that just ended rather than an older
        # closed ICU stay with a later admission timestamp.
        return max(
            patient_encounters,
            key=lambda item: item.discharged_at or item.admitted_at,
            default=None,
        )

    primary = dashboard(None, db)
    rows = []
    ward_counts: dict[str, int] = {}
    active_encounters = [item for item in encounters if item.status == "active"]
    for encounter in active_encounters:
        ward_counts[encounter.ward or "Unassigned"] = ward_counts.get(encounter.ward or "Unassigned", 0) + 1

    for patient in patients:
        encounter = latest_encounter(patient.id)
        patient_alerts = [item for item in alerts if item.patient_id == patient.id and item.status == "open"]
        patient_tasks = [item for item in tasks if item.patient_id == patient.id and item.status not in {"completed", "cancelled"}]
        patient_overdue = [
            item for item in patient_tasks if item.due_at and item.due_at < now
        ]
        patient_escalated = [item for item in patient_tasks if (item.escalation_level or 0) > 0]
        patient_drafts = [
            item
            for item in drafts
            if item.patient_id == patient.id
            and item.status in {"draft_ready", "human_edited", "model_unavailable"}
        ]
        patient_docs = [
            item
            for item in documents
            if item.patient_id == patient.id
            and item.ocr_status in {"needs_confirmation", "pending"}
        ]
        patient_referrals = [
            item for item in referrals if item.patient_id == patient.id and item.status in {"sent", "acknowledged"}
        ]
        patient_investigations = [
            item for item in investigations if item.patient_id == patient.id and item.status == "approved"
        ]
        claim_gaps = 0
        if patient.id == "pat_ravi":
            claim_gaps = primary["operational"]["claim_gaps"]
        flags = []
        if any(item.severity == "critical" for item in patient_alerts):
            flags.append("critical alert")
        if patient_overdue:
            flags.append("overdue task")
        if patient_escalated:
            flags.append("escalated")
        if patient_drafts:
            flags.append("draft review")
        if patient_referrals:
            flags.append("referral open")
        rows.append(
            {
                "patient_id": patient.id,
                "name": patient.name,
                "mrn": patient.mrn,
                "age": patient.age,
                "sex": patient.sex,
                "encounter_id": encounter.id if encounter else None,
                "kind": encounter.kind if encounter else None,
                "ward": encounter.ward if encounter else None,
                "bed": encounter.bed if encounter else None,
                "encounter_status": encounter.status if encounter else "no encounter",
                "open_alerts": len(patient_alerts),
                "critical_alerts": sum(1 for item in patient_alerts if item.severity == "critical"),
                "overdue_tasks": len(patient_overdue),
                "escalated_tasks": len(patient_escalated),
                "pending_drafts": len(patient_drafts),
                "pending_documents": len(patient_docs),
                "open_referrals": len(patient_referrals),
                "pending_investigations": len(patient_investigations),
                "claim_gaps": claim_gaps,
                "flags": flags,
            }
        )

    overdue_total = sum(1 for item in tasks if item.status not in {"completed", "cancelled"} and item.due_at and item.due_at < now)
    open_alert_total = sum(1 for item in alerts if item.status == "open")
    critical_alert_total = sum(1 for item in alerts if item.status == "open" and item.severity == "critical")
    escalated_total = sum(
        1
        for item in tasks
        if item.status not in {"completed", "cancelled"} and (item.escalation_level or 0) > 0
    )
    pending_draft_total = sum(
        1 for item in drafts if item.status in {"draft_ready", "human_edited", "model_unavailable"}
    )
    pending_document_total = sum(1 for item in documents if item.ocr_status in {"needs_confirmation", "pending"})
    pending_referral_total = sum(1 for item in referrals if item.status in {"sent", "acknowledged"})
    pending_investigation_total = sum(1 for item in investigations if item.status == "approved")
    recent_audit = list(
        db.scalars(select(AuditEntry).order_by(AuditEntry.created_at.desc()).limit(12))
    )
    return {
        "hospital": {"name": "MediBytes Demo Hospital", "as_of": now.isoformat()},
        "summary": {
            "active_encounters": len(active_encounters),
            "patients": len(patients),
            "wards": ward_counts,
            "pending_drafts": pending_draft_total,
            "overdue_tasks": overdue_total,
            "escalated_tasks": escalated_total,
            "open_alerts": open_alert_total,
            "critical_alerts": critical_alert_total,
            "pending_documents": pending_document_total,
            "open_referrals": pending_referral_total,
            "pending_investigations": pending_investigation_total,
            "claim_gaps": primary["operational"]["claim_gaps"],
            "discharge_reviews": sum(
                1
                for item in drafts
                if item.feature == "F9" and item.status in {"draft_ready", "human_edited", "model_unavailable"}
            ),
        },
        "patients": rows,
        "claim": primary["claim"],
        "illustrative": primary["illustrative"],
        "recent_audit": [_audit_dict(entry) for entry in recent_audit],
    }


@router.get("/dashboard")
def dashboard(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db, encounter_id)
    prep = claim_prep(db, patient, encounter, state)
    leak = leakage(db, patient, encounter, state)
    events = list_events(db, patient.id, encounter.id, approved_only=True, limit=1000)
    drafts_approved = db.scalar(
        select(func.count(Draft.id)).where(Draft.encounter_id == encounter.id, Draft.status == "approved")
    ) or 0
    drafts_total = db.scalar(
        select(func.count(Draft.id)).where(Draft.encounter_id == encounter.id)
    ) or 0
    open_alerts = sum(1 for alert in state["alerts"] if alert["status"] == "open")
    dismissed_alerts = sum(1 for alert in state["alerts"] if alert["status"] == "dismissed")
    tasks = state["tasks"]
    overdue = sum(
        1
        for task in tasks
        if task["due_at"]
        and task["status"] not in {"completed", "cancelled"}
        and task["due_at"] < utcnow().isoformat()
    )
    pending_docs = sum(1 for document in state["documents"] if document["ocr_status"] in {"needs_confirmation", "pending"})
    llm_calls = list(db.scalars(select(LLMCall).order_by(LLMCall.created_at.desc()).limit(200)))
    avg_latency = int(sum(call.latency_ms or 0 for call in llm_calls) / len(llm_calls)) if llm_calls else 0
    recent_audit = list(
        db.scalars(
            select(AuditEntry)
            .where(AuditEntry.patient_id == patient.id)
            .order_by(AuditEntry.created_at.desc())
            .limit(10)
        )
    )
    return {
        "patient": {"name": patient.name, "mrn": patient.mrn},
        "encounter": {"status": encounter.status, "ward": encounter.ward, "bed": encounter.bed},
        "operational": {
            "timeline_events": len([event for event in events if event.type != "transcript"]),
            "drafts_total": drafts_total,
            "drafts_approved": drafts_approved,
            "open_alerts": open_alerts,
            "dismissed_alerts": dismissed_alerts,
            "tasks_total": len(tasks),
            "tasks_overdue": overdue,
            "documents_pending": pending_docs,
            "claim_gaps": (
                len(prep["missing_documents"])
                + len(prep["unbilled_procedures"])
                + len(prep.get("underbilled_items", []))
                + len(prep["unsupported_items"])
                + len(prep.get("contradictions", []))
            ),
            "llm_calls": len(llm_calls),
            "avg_latency_ms": avg_latency,
        },
        "illustrative": {
            "clinician_minutes_saved": int(drafts_approved) * 12,
            "revenue_at_risk": sum(
                item.get("amount", 0) for item in prep["billed_items"] if not item.get("documentation_event_ids")
            ),
            "leakage_identified": sum(
                1 for item in leak["findings"] if item["billing_status"] in {"unbilled", "underbilled"}
            ),
            "note": "Illustrative KPIs, not measured outcomes.",
        },
        "claim": {
            "status": prep["status"],
            "missing_documents": [item["label"] for item in prep["missing_documents"]],
            "total_amount": prep["total_amount"],
            "expected_total_amount": prep.get("expected_total_amount", prep["total_amount"]),
            "underbilled_items": prep.get("underbilled_items", []),
            "underbilled_amount": prep.get("underbilled_amount", 0),
            "contradictions": prep.get("contradictions", []),
        },
        "recent_audit": [_audit_dict(entry) for entry in recent_audit],
    }


@router.get("/audit")
def audit_list(
    patient_id: str = "pat_ravi",
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    rows = list(
        db.scalars(
            select(AuditEntry)
            .where(AuditEntry.patient_id == patient_id)
            .order_by(AuditEntry.created_at.desc())
            .limit(limit)
        )
    )
    return {"audit": [_audit_dict(entry) for entry in rows], "count": len(rows)}


@router.get("/audit/{entity_id}")
def audit_entity(entity_id: str, db: Session = Depends(get_db)):
    rows = list(
        db.scalars(
            select(AuditEntry).where(AuditEntry.entity_id == entity_id).order_by(AuditEntry.created_at.desc())
        )
    )
    return {"audit": [_audit_dict(entry) for entry in rows]}


# --------------------------------------------------------------------------
# Demo control
# --------------------------------------------------------------------------
@router.get("/demo/status")
def demo_status(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    return {
        "patient": patient.name,
        "encounter": encounter.id,
        "events": len(list_events(db, patient.id, encounter.id, approved_only=True, limit=1000)),
        "mode": settings.effective_llm_mode,
        "demo_now": clock.now().replace(microsecond=0).isoformat(),
        "server_now": clock.real_utcnow().replace(microsecond=0).isoformat(),
    }


@router.post("/demo/reset")
def demo_reset(mode: Literal["start", "rehearsal"] = "rehearsal", db: Session = Depends(get_db)):
    reset_demo(db, mode)
    return {"ok": True, "mode": mode}
