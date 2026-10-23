from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..config import settings
from ..db import get_db, utcnow
from ..models import (
    Alert,
    AuditEntry,
    Document,
    Draft,
    Encounter,
    InvestigationRequest,
    LLMCall,
    Patient,
    Referral,
    Task,
)
from ..seed import reset_demo
from ..services import credits, identity
from ..services.medicines import unresolved_discrepancies
from ..services.revenue import claim_prep, leakage
from ..services.timeline import (
    get_state,
    list_events,
)
from .common import (
    _audit_dict,
    _state,
)

router = APIRouter()


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

    # The claim block is about the demo patient, not whoever X-Patient-Id names: this view is
    # hospital-wide. Pin the patient (keeping the acting user) while it is computed.
    tokens = identity.set_context(identity.acting_user().id, identity.DEFAULT_PATIENT_ID)
    try:
        primary = dashboard(None, db)
    finally:
        identity.reset_context(tokens)
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
            item for item in referrals if item.patient_id == patient.id and item.status in {"queued", "sent", "acknowledged"}
        ]
        patient_investigations = [
            item for item in investigations if item.patient_id == patient.id and item.status == "approved"
        ]
        patient_draft_discharges = [
            item
            for item in drafts
            if item.patient_id == patient.id
            and item.feature == "F9"
            and item.status in {"draft_ready", "human_edited"}
        ]
        discrepancies = 0
        if encounter:
            discrepancies = len(
                unresolved_discrepancies(db, patient, encounter, get_state(db, patient, encounter))
            )
        claim_gaps = 0
        if patient.id == identity.DEFAULT_PATIENT_ID:
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
        if patient_draft_discharges:
            flags.append("discharge draft")
        if discrepancies:
            flags.append("medicine discrepancy")
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
                "browsable": identity.is_browsable(patient.id),
                "open_alerts": len(patient_alerts),
                "critical_alerts": sum(1 for item in patient_alerts if item.severity == "critical"),
                "overdue_tasks": len(patient_overdue),
                "escalated_tasks": len(patient_escalated),
                "pending_tasks": len(patient_tasks),
                "pending_drafts": len(patient_drafts),
                "draft_discharges": len(patient_draft_discharges),
                "medicine_discrepancies": discrepancies,
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
    pending_referral_total = sum(1 for item in referrals if item.status in {"queued", "sent", "acknowledged"})
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
            "pending_tasks": sum(row["pending_tasks"] for row in rows),
            "draft_discharges": sum(row["draft_discharges"] for row in rows),
            "medicine_discrepancies": sum(row["medicine_discrepancies"] for row in rows),
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
    credits.reset(db)
    db.commit()
    return {"ok": True, "mode": mode}
