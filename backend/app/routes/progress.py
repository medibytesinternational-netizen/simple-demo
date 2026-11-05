"""Patient progress: overall (OPD to discharge) and daily (tasks and notes for one day).

Read-only. Every check answers one question about the record and points to the page where it
is fixed. "Verified" means approved by a clinician: a draft awaiting review or an OCR value no
person has confirmed is not verified.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..models import AuditEntry, Document, Draft, InvestigationRequest, Task, TimelineEvent
from ..services.approval.f09_discharge import discharge_readiness, open_critical_alerts, open_tasks
from ..services.timeline import get_encounter, get_patient, get_state

router = APIRouter()

PENDING_DRAFT = {"generating", "draft_ready", "human_edited", "model_unavailable"}
AWAITING_DOCUMENT = {"needs_confirmation", "pending", "needs_manual_entry"}
CLOSED = {"completed", "cancelled"}

# Records a clinician writes during the day, and how they are named on screen.
NOTE_TYPES = {
    "consult_note": "Consultation note",
    "admission_note": "Admission assessment",
    "round_note": "Ward round note",
    "progress_note": "Progress note",
    "nursing_summary": "Nursing summary",
    "nursing_chart": "Nursing chart",
    "investigation_review": "Investigation review",
    "procedure": "Procedure",
    "task_completed": "Completed task",
    "discharge_summary": "Discharge summary",
    "lab_result": "Lab result",
    "vitals": "Vitals",
}
DRAFT_TITLES = {
    "F1": "Consultation note", "F2": "Admission assessment", "F3": "Ward round note",
    "F4": "Progress note", "F7": "ICU flow sheet", "F9": "Discharge summary",
    "F10": "Investigation request", "F11": "Referral",
}


def _check(key: str, label: str, status: str, detail: str, link: str) -> dict[str, Any]:
    return {"key": key, "label": label, "status": status, "detail": detail, "link": link}


def _note(types: set[str], drafts: list[Draft], event_type: str, feature: str, label: str, link: str) -> dict[str, Any]:
    pending = [d for d in drafts if d.feature == feature and d.status in PENDING_DRAFT]
    if event_type in types and not pending:
        return _check(event_type, label, "done", "Approved by a clinician", link)
    if pending:
        return _check(event_type, label, "pending", "Draft waiting for clinician review", link)
    return _check(event_type, label, "missing", "Not recorded yet", link)


def overall_progress(db: Session, patient, encounter, state: dict[str, Any]) -> dict[str, Any]:
    events = [e for e in db.scalars(select(TimelineEvent).where(
        TimelineEvent.patient_id == patient.id, TimelineEvent.encounter_id == encounter.id, TimelineEvent.status == "approved"))]
    types = {e.type for e in events}
    drafts = list(db.scalars(select(Draft).where(Draft.patient_id == patient.id, Draft.encounter_id == encounter.id)))
    documents = list(db.scalars(select(Document).where(Document.patient_id == patient.id)))
    requests = list(db.scalars(select(InvestigationRequest).where(
        InvestigationRequest.patient_id == patient.id, InvestigationRequest.encounter_id == encounter.id)))
    allergy_verified = db.scalar(select(AuditEntry.id).where(
        AuditEntry.patient_id == patient.id, AuditEntry.action == "allergy_verified").limit(1)) is not None
    readiness = discharge_readiness(db, patient, encounter)
    alerts = open_critical_alerts(db, patient, encounter)
    tasks_open = open_tasks(db, patient, encounter)
    now = utcnow()
    overdue = [t for t in tasks_open if t.due_at and t.due_at < now]
    differences = readiness["warnings"]["unresolved_medicine_differences"]
    awaiting_docs = [d for d in documents if d.ocr_status in AWAITING_DOCUMENT]
    unreviewed = state.get("unreviewed_labs", [])
    pending_requests = [r for r in requests if r.status == "approved"]
    discharge_draft = next((d for d in drafts if d.feature == "F9"), None)

    stages = [
        ("opd", "OPD consultation", [
            _note(types, drafts, "consult_note", "F1", "Consultation note", "/notes?tab=consult"),
        ]),
        ("admission", "Admission", [
            _note(types, drafts, "admission_note", "F2", "Admission assessment", "/notes?tab=admission"),
            _check("allergy", "Allergy history verified",
                   "done" if allergy_verified or not patient.allergies else "pending",
                   "Verified against the source record" if allergy_verified else (
                       "No allergies recorded" if not patient.allergies else "Allergy not yet verified by a clinician"),
                   "/notes?tab=admission"),
        ]),
        ("ward", "Ward care", [
            _note(types, drafts, "round_note", "F3", "Ward round note", "/notes?tab=round"),
            _note(types, drafts, "progress_note", "F4", "Progress note", "/notes?tab=progress"),
        ]),
        ("investigations", "Investigations", [
            _check("labs", "Lab results reviewed", "done" if "lab_result" in types and not unreviewed else ("pending" if unreviewed else "missing"),
                   f"{len(unreviewed)} result(s) not reviewed" if unreviewed else ("All results reviewed" if "lab_result" in types else "No results yet"),
                   "/notes?tab=labs"),
            _check("requests", "Investigation requests sent", "pending" if pending_requests else "done",
                   f"{len(pending_requests)} request(s) not yet sent" if pending_requests else (
                       f"{len(requests)} request(s) sent" if requests else "None requested"),
                   "/documents?tab=requisition"),
        ]),
        ("documents", "Documents & records", [
            _check("documents", "Outside reports confirmed", "pending" if awaiting_docs else "done",
                   f"{len(awaiting_docs)} report(s) need a person to confirm the values" if awaiting_docs else (
                       f"{len(documents)} report(s) confirmed" if documents else "No outside reports"),
                   "/documents?tab=inbound"),
            _check("procedure", "Procedures documented", "done" if "procedure" in types else "missing",
                   "Documented" if "procedure" in types else "No procedure recorded", "/timeline"),
        ]),
        ("medicines", "Medicines", [
            _check("meds", "Home and inpatient medicines reconciled", "pending" if differences else "done",
                   f"{len(differences)} difference(s) undecided" if differences else "Reconciled", "/safety?tab=meds"),
        ]),
        ("safety", "Safety", [
            _check("alerts", "Critical alerts resolved", "pending" if alerts else "done",
                   f"{len(alerts)} critical alert(s) open" if alerts else "No open critical alerts", "/safety?tab=alerts"),
        ]),
        ("tasks", "Tasks", [
            _check("tasks", "Tasks completed", "pending" if tasks_open else "done",
                   (f"{len(tasks_open)} open" + (f", {len(overdue)} overdue" if overdue else "")) if tasks_open else "All tasks completed",
                   "/tasks"),
        ]),
        ("discharge", "Discharge", [
            _check("discharge_summary", "Discharge summary", "done" if "discharge_summary" in types else (
                "pending" if discharge_draft else "missing"),
                "Signed" if "discharge_summary" in types else ("Draft waiting for sign-off" if discharge_draft else "Not generated"),
                "/discharge"),
        ]),
    ]

    out_stages = []
    done = total = 0
    for key, title, checks in stages:
        statuses = {c["status"] for c in checks}
        stage_status = "done" if statuses == {"done"} else "missing" if statuses == {"missing"} else "pending"
        done += sum(1 for c in checks if c["status"] == "done")
        total += len(checks)
        out_stages.append({"key": key, "title": title, "status": stage_status, "checks": checks})
    return {"stages": out_stages, "done": done, "total": total, "percent": round(100 * done / total) if total else 0}


def _day(value: datetime | None) -> date | None:
    return value.date() if value else None


def daily_progress(db: Session, patient, encounter, day: date) -> dict[str, Any]:
    now = utcnow()
    tasks = list(db.scalars(select(Task).where(Task.patient_id == patient.id, Task.encounter_id == encounter.id)))
    day_tasks = [t for t in tasks if day in {_day(t.due_at), _day(t.created_at), _day(t.completed_at)}]
    task_rows = [{
        "id": t.id,
        "title": t.title,
        "category": t.category or "general",
        "priority": t.priority,
        "assigned_to": t.assigned_to,
        "assignee_role": t.assignee_role,
        "due_at": t.due_at.isoformat() if t.due_at else None,
        "status": t.status,
        "state": "done" if t.status == "completed" else "cancelled" if t.status == "cancelled" else (
            "overdue" if t.due_at and t.due_at < now else "open"),
        "completion_event_id": t.completion_event_id,
    } for t in sorted(day_tasks, key=lambda t: (t.due_at or t.created_at or now))]

    events = list(db.scalars(select(TimelineEvent).where(
        TimelineEvent.patient_id == patient.id, TimelineEvent.encounter_id == encounter.id,
        TimelineEvent.type.in_(list(NOTE_TYPES)))))
    note_rows = [{
        "id": e.id,
        "kind": NOTE_TYPES.get(e.type, e.type),
        "title": e.title,
        "author": e.author_name,
        "at": e.occurred_at.isoformat() if e.occurred_at else None,
        "state": "verified" if e.status == "approved" else "pending",
    } for e in sorted(events, key=lambda e: e.occurred_at or now) if _day(e.occurred_at) == day]

    drafts = list(db.scalars(select(Draft).where(Draft.patient_id == patient.id, Draft.encounter_id == encounter.id)))
    for d in drafts:
        if d.status in PENDING_DRAFT and _day(d.created_at) == day:
            note_rows.append({
                "id": d.id,
                "kind": DRAFT_TITLES.get(d.feature, d.feature),
                "title": f"{DRAFT_TITLES.get(d.feature, d.feature)} draft",
                "author": "MediBytes",
                "at": d.created_at.isoformat() if d.created_at else None,
                "state": "pending",
            })

    tasks_done = sum(1 for t in task_rows if t["state"] in {"done", "cancelled"})
    notes_verified = sum(1 for n in note_rows if n["state"] == "verified")
    return {
        "date": day.isoformat(),
        "tasks": task_rows,
        "notes": note_rows,
        "tasks_done": tasks_done,
        "tasks_total": len(task_rows),
        "notes_verified": notes_verified,
        "notes_total": len(note_rows),
        "complete": tasks_done == len(task_rows) and notes_verified == len(note_rows),
    }


def stay_days(encounter) -> list[str]:
    start = (encounter.admitted_at or utcnow()).date()
    end = (encounter.discharged_at or utcnow()).date()
    days, current = [], start
    while current <= end and len(days) < 120:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


@router.get("/patients/{patient_id}/progress")
def patient_progress(patient_id: str, date: str | None = None, db: Session = Depends(get_db)):
    patient = get_patient(db, patient_id)
    encounter = get_encounter(db)
    if not patient or not encounter:
        raise HTTPException(404, "Patient or encounter not found")
    try:
        day = datetime.fromisoformat(date).date() if date else utcnow().date()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    state = get_state(db, patient, encounter)
    return {
        "patient_id": patient.id,
        "overall": overall_progress(db, patient, encounter, state),
        "daily": daily_progress(db, patient, encounter, day),
        "days": stay_days(encounter),
    }
