"""F15 Task and escalation engine: created, assigned, acknowledged, completed, then escalates what stalls.

PRD rule 4: a task is not a completion. These tests prove the transition table, the reasons, the
assignee rule and the automatic escalation.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app import background
from app.db import SessionLocal, utcnow
from app.models import Task

NURSE = {"X-User-Id": "u_anita"}
MGMT = {"X-User-Id": "u_mgmt"}
PHARMACIST = {"X-User-Id": "u_dev"}
NURSE_NAME = "Nurse Anita Rao"

STATES = ["proposed", "accepted", "acknowledged", "in_progress", "completed", "cancelled"]
ALLOWED = {
    "proposed": {"accepted", "cancelled"},
    "accepted": {"acknowledged", "cancelled"},
    "acknowledged": {"in_progress", "completed", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}
PAIRS = [(a, b) for a in STATES for b in STATES]
REASON = "Patient waiting too long"


def _make(client, **body) -> dict:
    payload = {"title": "F15 task", "owner": NURSE_NAME, **body}
    response = client.post("/api/tasks", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _insert(status: str, assigned_to: str | None = NURSE_NAME, due_in_hours: float = 24, tid: str | None = None) -> str:
    """A task in any state, written directly (the API creates tasks as accepted)."""
    db = SessionLocal()
    try:
        task = Task(
            id=tid or f"tsk_f15_{status}_{assigned_to is None}_{int(due_in_hours * 10)}",
            patient_id="pat_ravi",
            encounter_id="enc_ipd_1",
            title="F15 inserted task",
            detail="",
            status=status,
            priority="routine",
            due_at=utcnow() + timedelta(hours=due_in_hours),
            owner=assigned_to,
            assigned_to=assigned_to,
            created_by="test",
            escalation_level=0,
        )
        db.merge(task)
        db.commit()
        return task.id
    finally:
        db.close()


def _row(task_id: str) -> dict:
    """The task as stored, read without going through GET /api/tasks (which also sweeps)."""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        return {
            "status": task.status,
            "level": task.escalation_level or 0,
            "reason": task.escalation_reason,
            "completed_at": task.completed_at,
            "acknowledged_by": task.acknowledged_by,
            "acknowledged_at": task.acknowledged_at,
        }
    finally:
        db.close()


def _audit(client, task_id: str, action: str) -> list[dict]:
    rows = client.get(f"/api/audit/{task_id}").json()["audit"]
    return [row for row in rows if row["action"] == action]


# ---------------- transition table ----------------

@pytest.mark.parametrize("old,new", PAIRS)
def test_task_status_follows_the_transition_table(client, old, new):
    task_id = _insert(old, tid=f"tsk_f15_matrix_{old}_{new}")
    response = client.patch(f"/api/tasks/{task_id}", json={"status": new}, headers=NURSE)
    if new in ALLOWED[old]:
        assert response.status_code == 200, response.text
        assert response.json()["status"] == new
        assert _row(task_id)["status"] == new
    else:
        assert response.status_code == 409, response.text
        assert old in response.json()["detail"]
        assert _row(task_id)["status"] == old


def test_task_cannot_skip_acknowledgement(client):
    task = _make(client)
    response = client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"}, headers=NURSE)
    assert response.status_code == 409
    assert "acknowledged" in response.json()["detail"]
    assert _row(task["id"])["status"] == "accepted"
    assert _row(task["id"])["completed_at"] is None


def test_completing_without_acknowledgement_is_refused_even_when_started(client):
    task = _make(client)
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"}, headers=NURSE).status_code == 409
    assert _row(task["id"])["status"] == "accepted"


def test_task_runs_the_whole_path_with_the_right_people_recorded(client):
    task = _make(client)
    assert client.post(f"/api/tasks/{task['id']}/acknowledge", headers=NURSE).status_code == 200
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"}, headers=NURSE).status_code == 200
    done = client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"}, headers=NURSE)
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "completed"
    assert body["acknowledged_by"] == NURSE_NAME
    assert body["completed_at"]
    changed = _audit(client, task["id"], "task_status_changed")
    assert {row["after"]["status"] for row in changed} == {"in_progress", "completed"}
    assert all(row["actor_name"] == NURSE_NAME for row in changed)


def test_acknowledge_only_works_on_an_accepted_task(client):
    proposed = _insert("proposed", tid="tsk_f15_ack_proposed")
    response = client.post(f"/api/tasks/{proposed}/acknowledge", headers=NURSE)
    assert response.status_code == 409
    assert _row(proposed)["status"] == "proposed"


# ---------------- assignee rule ----------------

def test_only_the_assignee_can_acknowledge(client):
    task = _make(client)  # assigned to the nurse; the default user is the doctor
    refused = client.post(f"/api/tasks/{task['id']}/acknowledge")
    assert refused.status_code == 403
    assert _row(task["id"])["status"] == "accepted"
    assert _row(task["id"])["acknowledged_by"] is None
    ok = client.post(f"/api/tasks/{task['id']}/acknowledge", headers=NURSE)
    assert ok.status_code == 200
    assert ok.json()["acknowledged_by"] == NURSE_NAME
    assert ok.json()["status"] == "acknowledged"


def test_acknowledging_through_patch_is_also_assignee_only(client):
    task = _make(client)
    refused = client.patch(f"/api/tasks/{task['id']}", json={"status": "acknowledged"})
    assert refused.status_code == 403
    assert _row(task["id"])["status"] == "accepted"
    allowed = client.patch(f"/api/tasks/{task['id']}", json={"status": "acknowledged"}, headers=NURSE)
    assert allowed.status_code == 200


def test_actor_in_the_body_is_ignored_when_acknowledging(client):
    task = _make(client)
    response = client.post(f"/api/tasks/{task['id']}/acknowledge", json={"actor": NURSE_NAME})
    assert response.status_code == 403
    assert _row(task["id"])["acknowledged_by"] is None


def test_unassigned_task_cannot_be_acknowledged(client):
    task_id = _insert("accepted", assigned_to=None, tid="tsk_f15_unassigned")
    response = client.post(f"/api/tasks/{task_id}/acknowledge", headers=NURSE)
    assert response.status_code == 400
    assert "Assign" in response.json()["detail"]


def test_management_cannot_create_tasks(client):
    before = len(client.get("/api/tasks").json()["tasks"])
    assert client.post("/api/tasks", json={"title": "Not allowed"}, headers=MGMT).status_code == 403
    assert len(client.get("/api/tasks").json()["tasks"]) == before


# ---------------- escalation ----------------

def test_overdue_task_escalates_without_a_manual_sweep(client):
    task = _make(client, due_in_hours=-6)
    assert _row(task["id"])["level"] == 0  # nothing has swept yet
    listed = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    assert listed[task["id"]]["escalation_level"] == 1
    assert listed[task["id"]]["escalation_reason"].startswith("Automatically escalated after")


def test_background_job_takes_late_tasks_to_the_right_level_and_leaves_others(client):
    late3 = _make(client, due_in_hours=-3)["id"]
    late9 = _make(client, due_in_hours=-9)["id"]
    future = _make(client, due_in_hours=5)["id"]
    finished = _make(client, due_in_hours=-6)["id"]
    assert client.post(f"/api/tasks/{finished}/acknowledge", headers=NURSE).status_code == 200
    assert client.patch(f"/api/tasks/{finished}", json={"status": "completed"}, headers=NURSE).status_code == 200
    assert "task-escalation" in background.JOBS
    assert [_row(i)["level"] for i in (late3, late9, future, finished)] == [0, 0, 0, 0]

    count = background.run_job("task-escalation")

    assert _row(late3)["level"] == 1
    assert _row(late9)["level"] == 2
    assert _row(future)["level"] == 0
    assert _row(finished)["level"] == 0
    assert count >= 2
    assert _row(late3)["reason"].startswith("Automatically escalated after 3.")
    assert _row(late9)["reason"].startswith("Automatically escalated after 9.")
    entry = _audit(client, late9, "task_escalated")
    assert len(entry) == 1
    assert entry[0]["actor_name"] == "Escalation engine"
    assert entry[0]["actor_type"] == "system"
    assert entry[0]["after"]["escalation_level"] == 2

    background.run_job("task-escalation")  # nothing new to raise
    assert len(_audit(client, late9, "task_escalated")) == 1
    assert len(_audit(client, late3, "task_escalated")) == 1


def test_manual_sweep_route_uses_the_same_sweep(client):
    late = _make(client, due_in_hours=-9)["id"]
    response = client.post("/api/tasks/escalations/run")
    assert response.status_code == 200
    body = response.json()
    assert late in [t["id"] for t in body["escalated"]]
    assert body["count"] == len(body["escalated"])
    assert _row(late)["level"] == 2
    again = client.post("/api/tasks/escalations/run").json()
    assert late not in [t["id"] for t in again["escalated"]]


def test_manual_escalation_needs_a_reason(client):
    task = _make(client)
    url = f"/api/tasks/{task['id']}/escalate"
    assert client.post(url, json={}).status_code == 422
    assert client.post(url).status_code == 422
    assert client.post(url, json={"reason": "too short"}).status_code == 422  # 9 characters
    assert client.post(url, json={"reason": "   short    "}).status_code == 422  # 5 after stripping
    assert _row(task["id"])["level"] == 0
    assert _audit(client, task["id"], "task_escalated") == []


def test_manual_escalation_stores_the_reason(client):
    task = _make(client)
    response = client.post(f"/api/tasks/{task['id']}/escalate", json={"reason": "  Bed needed urgently  "})
    assert response.status_code == 200
    assert response.json()["escalation_level"] == 1
    assert response.json()["escalation_reason"] == "Bed needed urgently"
    assert _row(task["id"])["reason"] == "Bed needed urgently"
    entry = _audit(client, task["id"], "task_escalated")[0]
    assert entry["after"]["escalation_reason"] == "Bed needed urgently"
    assert entry["actor_name"] == "Dr. Meera Shah"
    assert entry["after"]["kind"] == "manual"


# ---------------- reopen ----------------

def test_completed_task_cannot_be_reopened_without_a_reason(client):
    task = _make(client)
    tid = task["id"]
    assert client.post(f"/api/tasks/{tid}/acknowledge", headers=NURSE).status_code == 200
    assert client.patch(f"/api/tasks/{tid}", json={"status": "completed"}, headers=NURSE).status_code == 200
    for status in ("proposed", "accepted", "in_progress"):
        assert client.patch(f"/api/tasks/{tid}", json={"status": status}, headers=NURSE).status_code == 409
    url = f"/api/tasks/{tid}/reopen"
    assert client.post(url, headers=NURSE).status_code == 422
    assert client.post(url, json={}, headers=NURSE).status_code == 422
    assert client.post(url, json={"reason": "too short"}, headers=NURSE).status_code == 422
    assert _row(tid)["status"] == "completed"

    ok = client.post(url, json={"reason": "Result was entered on the wrong patient"}, headers=NURSE)
    assert ok.status_code == 200
    body = ok.json()
    assert body["status"] == "accepted"
    assert body["completed_at"] is None
    assert body["acknowledged_by"] is None  # must be acknowledged again
    entry = _audit(client, tid, "task_reopened")
    assert len(entry) == 1
    assert entry[0]["after"]["reason"] == "Result was entered on the wrong patient"
    assert entry[0]["before"]["status"] == "completed"
    assert entry[0]["actor_name"] == NURSE_NAME

    again = client.post(url, json={"reason": "Trying a second reopen"}, headers=NURSE)
    assert again.status_code == 409  # works once: the task is open now


def test_cancelled_task_can_be_reopened_and_open_task_cannot(client):
    task = _make(client)
    tid = task["id"]
    url = f"/api/tasks/{tid}/reopen"
    assert client.post(url, json={"reason": "Not finished at all"}, headers=NURSE).status_code == 409
    assert client.patch(f"/api/tasks/{tid}", json={"status": "cancelled"}, headers=NURSE).status_code == 200
    ok = client.post(url, json={"reason": "Cancelled by mistake"}, headers=NURSE)
    assert ok.status_code == 200
    assert ok.json()["status"] == "accepted"


def test_management_cannot_reopen_a_task(client):
    task = _make(client)
    tid = task["id"]
    client.patch(f"/api/tasks/{tid}", json={"status": "cancelled"}, headers=NURSE)
    response = client.post(f"/api/tasks/{tid}/reopen", json={"reason": "Management should not do this"}, headers=MGMT)
    assert response.status_code == 403
    assert _row(tid)["status"] == "cancelled"
