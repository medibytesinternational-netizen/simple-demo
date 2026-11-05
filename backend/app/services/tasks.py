"""Task and escalation engine (F15).

A task moves along a fixed path: proposed, accepted, acknowledged, in progress, completed. A task is
not a completion (PRD rule 4): nothing skips acknowledgement, and a finished task only comes back
through ``reopen`` with a reason. Overdue work escalates by itself through the background job.

There is one acting user, the doctor. Assignment is data: a task keeps the assignee's name
("Nurse Anita Rao") but the doctor acknowledges, works, escalates and reopens it on the assignee's
behalf. The stored assignee fields never change; the audit entry names the doctor as the actor and
carries ``on_behalf_of`` (in ``meta`` and ``after``) when the assignee is someone else. Overdue
escalation is not on behalf of anyone: its actor is the "Escalation engine".
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import background
from ..db import utcnow
from ..models import Task
from .identity import TASK_ROLES, acting_name, acting_user
from .timeline import add_audit, add_event

MIN_REASON = 10
CLOSED = {"completed", "cancelled"}

TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"accepted", "cancelled"},
    "accepted": {"acknowledged", "cancelled"},
    "acknowledged": {"in_progress", "completed", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

CATEGORY_LABELS = {
    "general": "General",
    "lab": "Lab report",
    "ct": "CT scan",
    "mri": "MRI",
    "xray": "X-ray",
    "ultrasound": "Ultrasound",
    "ecg": "ECG",
}

LEVEL_ONE_HOURS = 2
LEVEL_TWO_HOURS = 8


def _clean_reason(value: str) -> str:
    reason = (value or "").strip()
    if len(reason) < MIN_REASON:
        raise ValueError(f"Give a reason of at least {MIN_REASON} characters")
    return reason


class EscalateRequest(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _clean_reason(value)


class ReopenRequest(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _clean_reason(value)


def check_transition(task: Task, new_status: str) -> None:
    allowed = TRANSITIONS.get(task.status or "", set())
    if new_status in allowed:
        return
    if task.status in CLOSED:
        hint = "Reopen it with a reason to work on it again."
    else:
        hint = "Allowed next: " + ", ".join(sorted(allowed)) + "."
    raise HTTPException(
        409,
        f"Task is {task.status}; it cannot move to {new_status}. {hint}",
    )


def role_for_assignee(name: str | None) -> str | None:
    """Infer the receiving role from an assignee name when the caller did not give one."""
    if not name:
        return None
    lowered = name.lower()
    if lowered.startswith("nurse"):
        return "nurse"
    if lowered.startswith("dr.") and name != "Dr. Meera Shah":
        return "senior_doctor"
    return None


def visible_to_actor(task: Task) -> bool:
    """Role-based viewing: the chief sees every task; staff see only work given to their role."""
    user = acting_user()
    if user.role not in TASK_ROLES:
        return True
    return task.assignee_role == user.role or task.assigned_to == user.name


def require_own_task(task: Task) -> None:
    """Senior doctors and nurses may work only tasks given to them (403 otherwise)."""
    if not visible_to_actor(task):
        raise HTTPException(403, f"{acting_name()} may only work tasks assigned to their role")


def queue_key(task: Task) -> tuple:
    """Queue order: bumped tasks first, then urgent before normal, then the earliest due."""
    urgent = 0 if task.priority in {"urgent", "critical"} else 1
    due = task.due_at.isoformat() if task.due_at else "9999"
    return (-(task.queue_rank or 0), urgent, due)


def bump_urgent(db: Session, task: Task) -> Task:
    """Mark a task urgent and move it to the head of the queue."""
    if task.status in CLOSED:
        raise HTTPException(409, f"Task is {task.status}; reopen it before moving it up the queue")
    top = max((t.queue_rank or 0) for t in db.scalars(select(Task).where(Task.encounter_id == task.encounter_id))) if task.encounter_id else 0
    before = {"priority": task.priority, "queue_rank": task.queue_rank or 0}
    task.priority = "urgent"
    task.queue_rank = top + 1
    add_audit(
        db,
        "task_marked_urgent",
        "task",
        task.id,
        task.patient_id,
        actor_name=acting_name(),
        before=before,
        after={"priority": task.priority, "queue_rank": task.queue_rank, "title": task.title},
    )
    return task


def _record_in_chart(db: Session, task: Task) -> None:
    """A finished task becomes part of the patient chart."""
    label = CATEGORY_LABELS.get(task.category or "general", "General")
    event = add_event(
        db,
        patient_id=task.patient_id,
        encounter_id=task.encounter_id,
        type="task_completed",
        subtype=task.category or "general",
        title=f"{label} task completed: {task.title}",
        body_text=(task.detail or "").strip() or f"{task.title} completed by {acting_name()}.",
        payload={
            "task_id": task.id,
            "category": task.category or "general",
            "priority": task.priority,
            "assigned_to": task.assigned_to,
            "assignee_role": task.assignee_role,
            "completed_by": acting_name(),
        },
        source="task",
    )
    task.completion_event_id = event.id


def _behalf(task: Task) -> dict:
    """``on_behalf_of`` for the audit trail: the assignee, when someone other than the actor."""
    if task.assigned_to and task.assigned_to != acting_name():
        return {"on_behalf_of": task.assigned_to}
    return {}


def acknowledge(db: Session, task: Task) -> Task:
    """The acting doctor acknowledges an accepted task on behalf of its assignee.

    The task must be assigned (400) and accepted (409). ``acknowledged_by`` keeps the assignee's
    name; the audit actor is the doctor and ``on_behalf_of`` is the assignee.
    """
    if not task.assigned_to:
        raise HTTPException(400, "Assign the task before it can be acknowledged")
    check_transition(task, "acknowledged")
    before = {"status": task.status}
    task.status = "acknowledged"
    task.acknowledged_at = utcnow()
    task.acknowledged_by = task.assigned_to
    behalf = _behalf(task)
    add_audit(
        db,
        "task_acknowledged",
        "task",
        task.id,
        task.patient_id,
        actor_name=acting_name(),
        before=before,
        after={"status": task.status, "title": task.title, **behalf},
        meta=behalf,
    )
    return task


def change_status(db: Session, task: Task, new_status: str) -> Task:
    """Move a task along the path; the doctor acts on behalf of the assignee."""
    if new_status == "acknowledged":
        return acknowledge(db, task)
    check_transition(task, new_status)
    before = {"status": task.status}
    task.status = new_status
    behalf = _behalf(task)
    after = {"status": task.status, "title": task.title, **behalf}
    if new_status == "completed":
        task.completed_at = utcnow()
        if task.assigned_to:
            after["completed_by"] = task.assigned_to
        _record_in_chart(db, task)
        after["chart_event_id"] = task.completion_event_id
    add_audit(
        db,
        "task_status_changed",
        "task",
        task.id,
        task.patient_id,
        actor_name=acting_name(),
        before=before,
        after=after,
        meta=behalf,
    )
    return task


def escalate(db: Session, task: Task, reason: str) -> Task:
    """Manual escalation by the doctor (on behalf of the assignee); the reason was already checked."""
    before = {"escalation_level": task.escalation_level or 0}
    task.escalation_level = min((task.escalation_level or 0) + 1, 2)
    task.escalated_at = utcnow()
    task.escalation_reason = reason
    add_audit(
        db,
        "task_escalated",
        "task",
        task.id,
        task.patient_id,
        actor_name=acting_name(),
        before=before,
        after={
            "escalation_level": task.escalation_level,
            "escalation_reason": task.escalation_reason,
            "kind": "manual",
            **_behalf(task),
        },
        meta=_behalf(task),
    )
    return task


def reopen(db: Session, task: Task, reason: str) -> Task:
    """Reopen a closed task, with a reason, as the doctor on behalf of the assignee."""
    if task.status not in CLOSED:
        raise HTTPException(409, f"Task is {task.status}; only completed or cancelled tasks can be reopened")
    before = {
        "status": task.status,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "acknowledged_by": task.acknowledged_by,
    }
    task.status = "accepted"
    task.completed_at = None
    task.acknowledged_at = None
    task.acknowledged_by = None
    add_audit(
        db,
        "task_reopened",
        "task",
        task.id,
        task.patient_id,
        actor_name=acting_name(),
        before=before,
        after={"status": task.status, "title": task.title, "reason": reason, **_behalf(task)},
        meta={"reason": reason, **_behalf(task)},
    )
    return task


def run_escalations(db: Session) -> list[Task]:
    """Raise the level of every open task that is overdue. Does not commit."""
    now = utcnow()
    tasks = list(db.scalars(select(Task).where(Task.status.notin_(list(CLOSED)))))
    escalated: list[Task] = []
    for task in tasks:
        if not task.due_at:
            continue
        overdue_hours = (now - task.due_at).total_seconds() / 3600
        level = 2 if overdue_hours >= LEVEL_TWO_HOURS else 1 if overdue_hours >= LEVEL_ONE_HOURS else 0
        if level <= (task.escalation_level or 0):
            continue
        task.escalation_level = level
        task.escalated_at = now
        task.escalation_reason = f"Automatically escalated after {overdue_hours:.1f} hours overdue"
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
                "kind": "automatic",
            },
        )
    return escalated


def _escalation_job(db: Session) -> int:
    return len(run_escalations(db))


background.register("task-escalation", _escalation_job, 60)
