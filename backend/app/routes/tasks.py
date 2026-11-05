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
from ..services import tasks as engine
from ..services.tasks import EscalateRequest, ReopenRequest, run_escalations
from .common import (
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
    # Overdue work escalates on its own; reading the board is enough to bring it up to date.
    run_escalations(db)
    db.commit()
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
    rows = [task for task in db.scalars(stmt) if engine.visible_to_actor(task)]
    rows.sort(key=engine.queue_key)
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
        category=body.category,
        assignee_role=body.assignee_role or engine.role_for_assignee(body.owner),
        queue_rank=0,
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
        after={
            "title": task.title,
            "priority": task.priority,
            "due_at": task.due_at.isoformat(),
            "category": task.category,
            "assigned_to": task.assigned_to,
            "assignee_role": task.assignee_role,
        },
    )
    db.commit()
    return _task_dict(task)


@router.post("/tasks/{task_id}/urgent", dependencies=[Depends(require("manage_task"))])
def task_mark_urgent(task_id: str, db: Session = Depends(get_db)):
    """Urgent button: the task turns urgent and jumps to the head of the queue."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    engine.bump_urgent(db, task)
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
    task.assignee_role = engine.role_for_assignee(assigned)
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
def task_acknowledge(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    engine.require_own_task(task)
    engine.acknowledge(db, task)
    db.commit()
    return _task_dict(task)


@router.post("/tasks/{task_id}/escalate", dependencies=[Depends(require("manage_task"))])
def task_escalate(task_id: str, body: EscalateRequest, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    engine.escalate(db, task, body.reason)
    db.commit()
    return _task_dict(task)


@router.post("/tasks/escalations/run", dependencies=[Depends(require("manage_task"))])
def run_task_escalations(db: Session = Depends(get_db)):
    escalated = run_escalations(db)
    db.commit()
    return {"escalated": [_task_dict(task) for task in escalated], "count": len(escalated)}


@router.post("/tasks/{task_id}/reopen", dependencies=[Depends(require("work_task"))])
def task_reopen(task_id: str, body: ReopenRequest, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    engine.require_own_task(task)
    engine.reopen(db, task, body.reason)
    db.commit()
    return _task_dict(task)


@router.patch("/tasks/{task_id}", dependencies=[Depends(require("work_task"))])
def task_update(task_id: str, body: TaskUpdateRequest, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    engine.require_own_task(task)
    engine.change_status(db, task, body.status)
    db.commit()
    return _task_dict(task)
