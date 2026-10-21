from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import utcnow
from ..models import (
    Draft,
    Encounter,
    InvestigationRequest,
    LLMCall,
    Patient,
    Referral,
    Task,
    TimelineEvent,
)
from ..schemas import FEATURE_MODELS
from .timeline import add_audit, add_event, new_id

FEATURE_EVENT_TYPES = {
    "F1": "consult_note",
    "F2": "admission_note",
    "F3": "round_note",
    "F4": "progress_note",
    "F6": "reconciliation",
    "F7": "icu_flow_sheet",
    "F9": "discharge_summary",
    "F10": "investigation_request",
    "F11": "referral",
    "F12": "claim_review",
    "F13": "revenue_review",
}
FEATURE_TITLES = {
    "F1": "Consultation note",
    "F2": "Admission assessment",
    "F3": "Round handover",
    "F4": "Daily progress note",
    "F6": "Medication reconciliation",
    "F7": "ICU flow sheet",
    "F9": "Discharge summary",
    "F10": "Investigation and radiology request",
    "F11": "Smart referral",
    "F12": "Claim pack review",
    "F13": "Revenue leakage review",
}
SUPERSEDING_TYPES = {
    "consult_note",
    "admission_note",
    "round_note",
    "progress_note",
    "nursing_summary",
    "icu_flow_sheet",
    "investigation_review",
    "referral",
}


def _collect_evidence(content: Any) -> list[str]:
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"source_event_ids", "evidence_event_ids"} and isinstance(item, list):
                    found.extend(str(entry) for entry in item if str(entry).startswith("evt_"))
                elif key == "source_event_id" and isinstance(item, str) and item.startswith("evt_"):
                    found.append(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(content)
    return list(dict.fromkeys(found))


def _flatten_text(value: Any) -> list[str]:
    lines: list[str] = []

    def walk(item: Any, key: str = "") -> None:
        if isinstance(item, dict):
            if "text" in item and isinstance(item["text"], str) and item["text"].strip():
                lines.append(item["text"].strip())
                return
            for sub_key, sub_item in item.items():
                if sub_key in {"source_event_ids", "source_segment_ids", "evidence_event_ids", "bbox"}:
                    continue
                if isinstance(sub_item, (str, int, float)) and sub_key in {
                    "summary",
                    "heading",
                    "title",
                    "explanation",
                    "description",
                    "drug",
                    "dose",
                    "route",
                    "frequency",
                    "value",
                    "name",
                    "request_type",
                    "recipient",
                    "study",
                    "diagnosis",
                    "specialty",
                    "specialist",
                    "urgency",
                    "instructions",
                }:
                    lines.append(str(sub_item))
                else:
                    walk(sub_item, sub_key)
        elif isinstance(item, list):
            for sub_item in item:
                walk(sub_item, key)

    walk(value)
    return list(dict.fromkeys(lines))


def _clear_generated_authorship(value: Any) -> Any:
    """Model output may never claim that a clinician authored a sentence."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "human_authored":
                value[key] = False
            else:
                _clear_generated_authorship(item)
    elif isinstance(value, list):
        for item in value:
            _clear_generated_authorship(item)
    return value


def create_draft(
    db: Session,
    *,
    feature: str,
    patient: Patient,
    encounter: Encounter,
    content: dict[str, Any],
    llm_call: LLMCall | None = None,
    created_from_event_ids: list[str] | None = None,
) -> Draft:
    content = _clear_generated_authorship(content)
    draft = Draft(
        id=new_id("drf"),
        feature=feature,
        patient_id=patient.id,
        encounter_id=encounter.id,
        status="draft_ready",
        content=content,
        schema_version="v1",
        prompt_version=llm_call.prompt_version if llm_call else "v1",
        model=llm_call.model if llm_call else "cached",
        llm_call_id=llm_call.id if llm_call else None,
        evidence_event_ids=_collect_evidence(content),
        created_from_event_ids=created_from_event_ids or [],
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(draft)
    db.flush()
    add_audit(
        db,
        "draft_created",
        "draft",
        draft.id,
        patient.id,
        actor_type="model",
        actor_name=llm_call.model if llm_call else "Cached demo generator",
        after={
            "feature": feature,
            "status": draft.status,
            "evidence_count": len(draft.evidence_event_ids),
        },
        meta={
            "mode": llm_call.mode if llm_call else "cached",
            "prompt_version": draft.prompt_version,
            "latency_ms": llm_call.latency_ms if llm_call else 0,
        },
    )
    return draft


def update_draft(
    db: Session,
    draft: Draft,
    content: dict[str, Any],
    editor: str | None = None,
) -> Draft:
    if draft.status == "approved":
        raise ValueError("Approved drafts cannot be edited")
    model_cls = FEATURE_MODELS.get(draft.feature)
    if model_cls:
        content = model_cls.model_validate(content).model_dump(mode="json")
    before = {"status": draft.status, "content": draft.content}
    draft.content = content
    draft.status = "human_edited"
    draft.edited_by = editor or settings.demo_user
    draft.evidence_event_ids = _collect_evidence(content)
    draft.updated_at = utcnow()
    add_audit(
        db,
        "draft_edited",
        "draft",
        draft.id,
        draft.patient_id,
        before=before,
        after={"status": draft.status, "content": content},
    )
    return draft


def reject_draft(db: Session, draft: Draft, reason: str, actor: str | None = None) -> Draft:
    if len(reason.strip()) < 10:
        raise ValueError("A rejection reason of at least 10 characters is required")
    if draft.status == "approved":
        raise ValueError("Approved drafts cannot be rejected")
    draft.status = "rejected"
    draft.rejected_reason = reason.strip()
    draft.updated_at = utcnow()
    add_audit(
        db,
        "draft_rejected",
        "draft",
        draft.id,
        draft.patient_id,
        actor_name=actor or settings.demo_user,
        after={"reason": reason.strip()},
    )
    return draft


def _validate_citations(db: Session, content: dict[str, Any]) -> None:
    cited = _collect_evidence(content)
    if not cited:
        return
    existing = set(
        db.scalars(select(TimelineEvent.id).where(TimelineEvent.id.in_(cited))).all()
    )
    missing = [item for item in cited if item not in existing]
    if missing:
        raise ValueError(f"Unknown evidence event ids: {', '.join(missing[:5])}")


def approve_draft(
    db: Session,
    draft: Draft,
    content: dict[str, Any] | None,
    approver: str | None = None,
) -> TimelineEvent | None:
    if draft.status == "approved" and draft.committed_event_id:
        event = db.get(TimelineEvent, draft.committed_event_id)
        return event
    if draft.status == "rejected":
        raise ValueError("Rejected drafts cannot be approved")

    approver = approver or settings.demo_user
    if content is not None:
        model_cls = FEATURE_MODELS.get(draft.feature)
        if model_cls:
            content = model_cls.model_validate(content).model_dump(mode="json")
        draft.content = content
    payload = draft.content or {}
    _validate_citations(db, payload)
    if draft.feature == "F4":
        exam = (payload.get("exam") or {}).get("general") or {}
        plan = payload.get("plan") or {}
        if not str(exam.get("text", "")).strip() or not str(plan.get("text", "")).strip():
            raise ValueError(
                "F4 cannot be approved: the examination and plan are required. "
                "Edit the draft to document them first."
            )
    if draft.feature == "F2":
        allergies = payload.get("allergies_to_verify") or []
        unverified = [
            item.get("substance", "unknown")
            for item in allergies
            if isinstance(item, dict) and not item.get("verified")
        ]
        if unverified:
            raise ValueError(
                "F2 cannot be approved: verify the documented allergy record first "
                f"({', '.join(unverified)}). The model may not mark an allergy as verified."
            )
    if draft.feature == "F1":
        consent_events = db.scalars(
            select(TimelineEvent).where(
                TimelineEvent.patient_id == draft.patient_id,
                TimelineEvent.encounter_id == draft.encounter_id,
                TimelineEvent.type == "consent",
                TimelineEvent.status == "approved",
            )
        ).all()
        granted = any(
            (event.payload or {}).get("granted") is True for event in consent_events
        )
        if not granted:
            raise ValueError(
                "F1 cannot be approved: record the patient's consent for consultation "
                "capture before signing the note."
            )

    patient = db.get(Patient, draft.patient_id)
    encounter = db.get(Encounter, draft.encounter_id) if draft.encounter_id else None
    if not patient or not encounter:
        raise ValueError("Patient or encounter missing")

    event_type = FEATURE_EVENT_TYPES.get(draft.feature, "note")
    title = FEATURE_TITLES.get(draft.feature, "Clinical note")
    body_text = "\n".join(_flatten_text(payload))
    event_payload = dict(payload)
    event_payload["draft_id"] = draft.id

    if draft.feature == "F10":
        indication = payload.get("indication") or {}
        request = InvestigationRequest(
            id=new_id("inv"),
            patient_id=patient.id,
            encounter_id=encounter.id,
            request_type=payload.get("request_type", "laboratory"),
            study=payload.get("study", "Investigation"),
            indication=indication.get("text", "") if isinstance(indication, dict) else str(indication),
            diagnosis=payload.get("diagnosis", ""),
            allergies_to_verify=payload.get("allergies_to_verify", []),
            priority=payload.get("priority", "routine"),
            instructions=payload.get("instructions", ""),
            status="approved",
            draft_id=draft.id,
            approved_by=approver,
            created_at=utcnow(),
        )
        db.add(request)
        db.flush()
        event_payload["request_id"] = request.id

    if draft.feature == "F11":
        question = payload.get("question") or {}
        history = payload.get("history") or {}
        referral = Referral(
            id=new_id("ref"),
            patient_id=patient.id,
            encounter_id=encounter.id,
            specialty=payload.get("specialty", "Specialist service"),
            specialist=payload.get("specialist", ""),
            question=question.get("text", "") if isinstance(question, dict) else str(question),
            history=history.get("text", "") if isinstance(history, dict) else str(history),
            urgency=payload.get("urgency", "routine"),
            status="sent",
            draft_id=draft.id,
            approved_by=approver,
            sent_at=utcnow(),
            created_at=utcnow(),
        )
        db.add(referral)
        db.flush()
        event_payload["referral_id"] = referral.id

    supersedes = None
    if event_type in SUPERSEDING_TYPES:
        previous = db.scalars(
            select(TimelineEvent)
            .where(
                TimelineEvent.patient_id == patient.id,
                TimelineEvent.encounter_id == encounter.id,
                TimelineEvent.type == event_type,
                TimelineEvent.status == "approved",
            )
            .order_by(TimelineEvent.occurred_at.desc())
        ).first()
        if previous:
            previous.status = "superseded"
            supersedes = previous.id

    event = add_event(
        db,
        patient_id=patient.id,
        encounter_id=encounter.id,
        type=event_type,
        subtype=draft.feature.lower(),
        title=title,
        body_text=body_text,
        payload=event_payload,
        source=draft.feature,
        author_type="model",
        author_name=approver,
        status="approved",
        confidence=None,
        occurred_at=utcnow(),
        approved_by=approver,
        supersedes_event_id=supersedes,
    )
    if draft.feature == "F3":
        nursing_entries = payload.get("nursing_entries", [])
        if nursing_entries:
            nursing_event = add_event(
                db,
                patient_id=patient.id,
                encounter_id=encounter.id,
                type="nursing_chart",
                subtype="f3",
                title="Nursing chart — round instructions",
                body_text="\n".join(
                    str(entry.get("text", "")) for entry in nursing_entries if isinstance(entry, dict)
                ),
                payload={
                    "round_event_id": event.id,
                    "entries": nursing_entries,
                },
                source="F3",
                author_type="model",
                author_name=approver,
                status="approved",
                approved_by=approver,
            )
            add_audit(
                db,
                "nursing_chart_committed",
                "timeline_event",
                nursing_event.id,
                patient.id,
                after={"round_event_id": event.id, "entries": len(nursing_entries)},
            )

    draft.status = "approved"
    draft.approved_by = approver
    draft.committed_event_id = event.id
    draft.updated_at = utcnow()

    if draft.feature == "F9":
        encounter.status = "discharged"
        encounter.discharged_at = utcnow()

    add_audit(
        db,
        "draft_approved",
        "draft",
        draft.id,
        patient.id,
        actor_type="user",
        actor_name=approver,
        before={"status": "draft_ready"},
        after={
            "status": "approved",
            "event_id": event.id,
            "feature": draft.feature,
            "title": title,
        },
        meta={
            "model": draft.model,
            "prompt_version": draft.prompt_version,
            "evidence_event_ids": draft.evidence_event_ids,
            "human_edited": bool(draft.edited_by),
        },
    )
    add_audit(
        db,
        "timeline_committed",
        "timeline_event",
        event.id,
        patient.id,
        after={"type": event.type, "title": event.title, "source": event.source},
    )
    return event


def accept_tasks(
    db: Session,
    draft: Draft,
    indices: list[int],
    actor: str | None = None,
) -> list[Task]:
    if draft.feature != "F3":
        raise ValueError("Only round drafts produce proposed tasks")
    proposed = (draft.content or {}).get("proposed_tasks", [])
    actor = actor or settings.demo_user
    created: list[Task] = []
    now = utcnow()
    for index in indices:
        if index < 0 or index >= len(proposed):
            continue
        item = proposed[index]
        existing = db.scalar(
            select(Task).where(
                Task.accepted_from_draft_id == draft.id,
                Task.title == item.get("title", ""),
            )
        )
        if existing:
            continue
        due_hours = int(item.get("due_in_hours", 24) or 24)
        task = Task(
            id=new_id("tsk"),
            patient_id=draft.patient_id,
            encounter_id=draft.encounter_id,
            title=item.get("title", "Round task")[:180],
            detail=item.get("detail", ""),
            status="accepted",
            priority=item.get("priority", "routine"),
            due_at=now + timedelta(hours=due_hours),
            owner=actor,
            source_event_id=draft.committed_event_id,
            accepted_from_draft_id=draft.id,
            created_by=actor,
            created_at=now,
        )
        db.add(task)
        created.append(task)
        add_audit(
            db,
            "task_accepted",
            "task",
            task.id,
            draft.patient_id,
            actor_name=actor,
            after={"title": task.title, "priority": task.priority, "due_at": task.due_at.isoformat()},
            meta={"draft_id": draft.id, "proposed_index": index},
        )
    db.flush()
    return created


def draft_to_dict(draft: Draft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "feature": draft.feature,
        "patient_id": draft.patient_id,
        "encounter_id": draft.encounter_id,
        "status": draft.status,
        "content": draft.content,
        "schema_version": draft.schema_version,
        "prompt_version": draft.prompt_version,
        "model": draft.model,
        "llm_call_id": draft.llm_call_id,
        "evidence_event_ids": draft.evidence_event_ids or [],
        "created_from_event_ids": draft.created_from_event_ids or [],
        "edited_by": draft.edited_by,
        "approved_by": draft.approved_by,
        "rejected_reason": draft.rejected_reason,
        "committed_event_id": draft.committed_event_id,
        "created_at": draft.created_at.isoformat(),
        "updated_at": draft.updated_at.isoformat(),
    }
