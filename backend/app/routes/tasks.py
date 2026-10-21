from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..services.timeline import require_open_encounter
from ..services.identity import require
from ..services.identity import acting_name
from ..db import get_db, utcnow
from ..models import (
    Task,
)
from ..services.timeline import (
    add_audit,
    new_id,
)
from .common import (
    TaskActionRequest,
    TaskAssignRequest,
    TaskCreateRequest,
    TaskUpdateRequest,
    _state,
    _task_dict,
)

router = APIRouter()


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


@router.post("/tasks", dependencies=[Depends(require("manage_task"))])
def task_create(body: TaskCreateRequest, db: Session = Depends(get_db)):
    patient, encounter, _ = _state(db)
    require_open_encounter(encounter)
    task = Task(
        id=new_id("tsk"),
        patient_id=patient.id,
        encounter_id=encounter.id,
        title=body.title.strip(),
        detail=body.detail.strip(),
        status="accepted",
        priority=body.priority,
        due_at=utcnow() + timedelta(hours=body.due_in_hours),
        owner=body.owner or acting_name(),
        assigned_to=body.owner or acting_name(),
        assigned_at=utcnow(),
        assigned_by=acting_name(),
        created_by=acting_name(),
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


@router.post("/tasks/{task_id}/assign", dependencies=[Depends(require("manage_task"))])
def task_assign(task_id: str, body: TaskAssignRequest, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    previous = task.owner
    assigned = body.assigned_to.strip() or None
    task.assigned_to = assigned
    task.owner = assigned
    task.assigned_at = utcnow() if assigned else None
    task.assigned_by = acting_name() if assigned else None
    add_audit(
        db,
        "task_assigned" if assigned else "task_unassigned",
        "task",
        task.id,
        task.patient_id,
        actor_name=acting_name(),
        before={"owner": previous},
        after={"assigned_to": assigned},
    )
    db.commit()
    return _task_dict(task)


@router.post("/tasks/{task_id}/acknowledge", dependencies=[Depends(require("work_task"))])
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
    task.acknowledged_by = acting_name()
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


@router.post("/tasks/{task_id}/escalate", dependencies=[Depends(require("manage_task"))])
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
        actor_name=acting_name(),
        after={
            "escalation_level": task.escalation_level,
            "escalation_reason": task.escalation_reason,
        },
    )
    db.commit()
    return _task_dict(task)


@router.post("/tasks/escalations/run", dependencies=[Depends(require("manage_task"))])
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


@router.patch("/tasks/{task_id}", dependencies=[Depends(require("work_task"))])
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
        task.acknowledged_by = acting_name()
    add_audit(
        db,
        "task_status_changed",
        "task",
        task.id,
        task.patient_id,
        actor_name=acting_name(),
        before=before,
        after={"status": task.status, "title": task.title},
    )
    db.commit()
    return _task_dict(task)
