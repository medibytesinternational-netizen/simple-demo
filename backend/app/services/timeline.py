from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .identity import acting_name, current_patient_id
from .. import clock
from ..db import utcnow
from ..models import (
    Alert,
    AuditEntry,
    Document,
    Encounter,
    Patient,
    Task,
    TimelineEvent,
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def get_patient(db: Session, patient_id: str | None = None) -> Patient:
    patient = db.get(Patient, patient_id or current_patient_id())
    if not patient:
        raise ValueError("Patient not found")
    return patient


def get_encounter(db: Session, encounter_id: str | None = None) -> Encounter:
    if encounter_id:
        encounter = db.get(Encounter, encounter_id)
        if not encounter:
            raise ValueError("Encounter not found")
        return encounter
    # The app is patient-centric: the default encounter belongs to the demo
    # patient, not whichever cohort patient happened to be admitted last.
    patient = get_patient(db)
    encounter = db.scalars(
        select(Encounter)
        .where(Encounter.patient_id == patient.id, Encounter.status == "active")
        .order_by(Encounter.admitted_at.desc())
    ).first()
    if not encounter:
        encounter = db.scalars(
            select(Encounter)
            .where(Encounter.patient_id == patient.id)
            .order_by(Encounter.discharged_at.desc(), Encounter.admitted_at.desc())
        ).first()
    if not encounter:
        encounter = db.scalars(select(Encounter).order_by(Encounter.admitted_at.desc())).first()
    if not encounter:
        raise ValueError("No encounter found")
    return encounter


class EncounterLocked(ValueError):
    """Raised for a clinical write to a discharged encounter; mapped to HTTP 409."""


# Features that write clinical content. Revenue drafts (F12, F13) are not locked:
# the PRD starts claim work after discharge.
LOCKED_FEATURES = {"F1", "F2", "F3", "F4", "F6", "F7", "F9", "F10", "F11"}


def require_open_encounter(encounter: Encounter) -> None:
    if encounter.status != "active":
        raise EncounterLocked(
            f"This encounter is {encounter.status} and its clinical record is locked. "
            "Only claim, document and follow-up work continues after discharge."
        )


def add_audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: str,
    patient_id: str | None = None,
    actor_type: str = "user",
    actor_name: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    meta: dict | None = None,
) -> AuditEntry:
    entry = AuditEntry(
        id=new_id("aud"),
        actor_type=actor_type,
        actor_name=actor_name or acting_name(),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        patient_id=patient_id,
        before=before or {},
        after=after or {},
        meta=meta or {},
        created_at=utcnow(),
    )
    db.add(entry)
    return entry


def add_event(
    db: Session,
    *,
    patient_id: str,
    encounter_id: str | None,
    type: str,
    title: str,
    body_text: str = "",
    payload: dict[str, Any] | None = None,
    subtype: str | None = None,
    source: str = "human",
    author_type: str = "human",
    author_name: str | None = None,
    status: str = "approved",
    confidence: float | None = None,
    occurred_at: datetime | None = None,
    approved_by: str | None = None,
    document_id: str | None = None,
    supersedes_event_id: str | None = None,
) -> TimelineEvent:
    event = TimelineEvent(
        id=new_id("evt"),
        patient_id=patient_id,
        encounter_id=encounter_id,
        type=type,
        subtype=subtype,
        title=title,
        body_text=body_text,
        payload=payload or {},
        source=source,
        author_type=author_type,
        author_name=author_name or acting_name(),
        status=status,
        confidence=confidence,
        supersedes_event_id=supersedes_event_id,
        occurred_at=occurred_at or utcnow(),
        created_at=utcnow(),
        approved_by=approved_by,
        approved_at=utcnow() if status == "approved" else None,
        document_id=document_id,
    )
    db.add(event)
    db.flush()
    return event


def list_events(
    db: Session,
    patient_id: str | None = None,
    encounter_id: str | None = None,
    *,
    approved_only: bool = True,
    limit: int = 300,
) -> list[TimelineEvent]:
    stmt = select(TimelineEvent).where(TimelineEvent.patient_id == (patient_id or current_patient_id()))
    if encounter_id:
        stmt = stmt.where(TimelineEvent.encounter_id == encounter_id)
    if approved_only:
        stmt = stmt.where(TimelineEvent.status.in_(["approved", "superseded"]))
    stmt = stmt.order_by(TimelineEvent.occurred_at.desc()).limit(limit)
    return list(db.scalars(stmt))


def get_event(db: Session, event_id: str) -> TimelineEvent:
    event = db.get(TimelineEvent, event_id)
    if not event:
        raise ValueError("Event not found")
    return event


def _medications(events: list[TimelineEvent], kinds: tuple[str, ...]) -> list[dict[str, Any]]:
    by_drug: dict[str, dict[str, Any]] = {}
    for event in sorted(events, key=lambda e: e.occurred_at):
        if event.type != "med_order":
            continue
        payload = event.payload or {}
        if payload.get("kind", "inpatient") not in kinds:
            continue
        drug = str(payload.get("drug", "")).strip()
        if not drug:
            continue
        status = payload.get("status", "active")
        record = {
            "event_id": event.id,
            "drug": drug,
            "dose": payload.get("dose", ""),
            "route": payload.get("route", ""),
            "frequency": payload.get("frequency", ""),
            "indication": payload.get("indication", ""),
            "kind": payload.get("kind", "inpatient"),
            "status": status,
            "started_at": event.occurred_at.isoformat(),
        }
        if status == "stopped":
            by_drug.pop(drug.lower(), None)
        else:
            by_drug[drug.lower()] = record
    return list(by_drug.values())


def _latest_labs(events: list[TimelineEvent]) -> list[dict[str, Any]]:
    latest: dict[str, tuple[datetime, TimelineEvent]] = {}
    for event in events:
        if event.type != "lab_result":
            continue
        payload = event.payload or {}
        name = str(payload.get("name", "")).lower()
        if not name:
            continue
        collected_raw = payload.get("collected_at") or event.occurred_at.isoformat()
        try:
            collected = datetime.fromisoformat(str(collected_raw).replace("Z", ""))
        except ValueError:
            collected = event.occurred_at
        if name not in latest or collected > latest[name][0]:
            latest[name] = (collected, event)
    results = []
    for name, (_, event) in latest.items():
        payload = event.payload or {}
        results.append(
            {
                "event_id": event.id,
                "name": payload.get("name", name),
                "value": payload.get("value"),
                "unit": payload.get("unit", ""),
                "reference_range": payload.get("reference_range", ""),
                "flag": payload.get("flag", "unknown"),
                "review_status": payload.get("review_status", "reviewed"),
                "collected_at": payload.get("collected_at", event.occurred_at.isoformat()),
            }
        )
    return sorted(results, key=lambda item: item["name"])


def get_state(
    db: Session,
    patient: Patient,
    encounter: Encounter,
) -> dict[str, Any]:
    events = list_events(db, patient.id, encounter.id, approved_only=True, limit=1000)
    home_meds = _medications(events, ("home",))
    current_meds = _medications(events, ("inpatient", "discharge"))
    labs = _latest_labs(events)
    unreviewed_labs = [lab for lab in labs if lab.get("review_status") == "unreviewed"]
    vitals_event = next((e for e in events if e.type == "vitals"), None)
    icu_entries = [
        {
            "category": (event.payload or {}).get("category", "other"),
            "label": (event.payload or {}).get("label", event.title),
            "value": (event.payload or {}).get("value", ""),
            "unit": (event.payload or {}).get("unit", ""),
            "recorded_at": (event.payload or {}).get("recorded_at", event.occurred_at.isoformat()),
            "device": (event.payload or {}).get("device", ""),
            "source_event_id": event.id,
            "confidence": event.confidence or 0.95,
        }
        for event in events
        if event.type == "device_reading"
    ]
    icu_entries.sort(key=lambda item: item.get("recorded_at", ""))
    tasks = list(
        db.scalars(
            select(Task)
            .where(Task.patient_id == patient.id, Task.encounter_id == encounter.id)
            .order_by(Task.created_at.desc())
        )
    )
    alerts = list(
        db.scalars(
            select(Alert)
            .where(Alert.patient_id == patient.id, Alert.encounter_id == encounter.id)
            .order_by(Alert.created_at.desc())
        )
    )
    documents = list(
        db.scalars(
            select(Document)
            .where(Document.patient_id == patient.id)
            .order_by(Document.uploaded_at.desc())
        )
    )
    notes = {
        key: next((e for e in events if e.type == key), None)
        for key in (
            "consult_note",
            "admission_note",
            "round_note",
            "progress_note",
            "nursing_summary",
            "investigation_review",
        )
    }
    discharge_event = next((e for e in events if e.type == "discharge_summary"), None)
    return {
        "patient": {
            "id": patient.id,
            "mrn": patient.mrn,
            "name": patient.name,
            "age": patient.age,
            "sex": patient.sex,
            "allergies": patient.allergies or [],
            "problems": patient.problems or [],
            "weight_kg": patient.weight_kg,
            "height_cm": patient.height_cm,
            "code_status": patient.code_status,
        },
        "encounter": {
            "id": encounter.id,
            "kind": encounter.kind,
            "ward": encounter.ward,
            "bed": encounter.bed,
            "attending": encounter.attending,
            "admitted_at": encounter.admitted_at.isoformat() if encounter.admitted_at else None,
            "discharged_at": encounter.discharged_at.isoformat() if encounter.discharged_at else None,
            "status": encounter.status,
        },
        "home_meds": home_meds,
        "active_meds": current_meds,
        "latest_labs": labs,
        "unreviewed_labs": unreviewed_labs,
        "vitals": {
            "event_id": vitals_event.id,
            "payload": vitals_event.payload,
            "occurred_at": vitals_event.occurred_at.isoformat(),
        }
        if vitals_event
        else None,
        "tasks": [
            {
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
                "is_overdue": bool(
                    task.due_at
                    and task.status not in {"completed", "cancelled"}
                    and task.due_at < clock.now()
                ),
            }
            for task in tasks
        ],
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
                "dismissal_reason": alert.dismissal_reason,
                "created_at": alert.created_at.isoformat(),
            }
            for alert in alerts
        ],
        "documents": [
            {
                "id": document.id,
                "filename": document.filename,
                "doc_type": document.doc_type,
                "ocr_status": document.ocr_status,
                "uploaded_at": document.uploaded_at.isoformat(),
                "field_count": len((document.extracted or {}).get("fields", [])),
            }
            for document in documents
        ],
        "notes": {
            key: {
                "event_id": event.id,
                "title": event.title,
                "occurred_at": event.occurred_at.isoformat(),
                "payload": event.payload,
            }
            for key, event in notes.items()
            if event
        },
        "icu_entries": icu_entries,
        "icu_shift_window": {
            "start": icu_entries[0]["recorded_at"] if icu_entries else "",
            "end": icu_entries[-1]["recorded_at"] if icu_entries else "",
        },
        "discharge_signed": bool(discharge_event),
        "discharge_event_id": discharge_event.id if discharge_event else None,
    }


def event_to_dict(event: TimelineEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "patient_id": event.patient_id,
        "encounter_id": event.encounter_id,
        "type": event.type,
        "subtype": event.subtype,
        "title": event.title,
        "body_text": event.body_text,
        "payload": event.payload or {},
        "source": event.source,
        "author_type": event.author_type,
        "author_name": event.author_name,
        "status": event.status,
        "confidence": event.confidence,
        "supersedes_event_id": event.supersedes_event_id,
        "occurred_at": event.occurred_at.isoformat(),
        "created_at": event.created_at.isoformat(),
        "approved_by": event.approved_by,
        "approved_at": event.approved_at.isoformat() if event.approved_at else None,
        "document_id": event.document_id,
    }
