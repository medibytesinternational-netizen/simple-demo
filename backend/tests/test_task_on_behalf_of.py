"""T2: the doctor works a task on behalf of its assignee.

Assignment stays as data ("Nurse Anita Rao"); nobody logs in as the assignee. The doctor acknowledges,
works, escalates and reopens the task; the stored assignee fields do not change and the audit entry
names the doctor as the actor with ``on_behalf_of`` set to the assignee. Overdue escalation is the
system's own act and carries no ``on_behalf_of``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import SessionLocal, utcnow
from app.models import AuditEntry, Task

DOCTOR_NAME = "Dr. Meera Shah"
NURSE_NAME = "Nurse Anita Rao"
PHARMACIST_NAME = "Pharmacist Dev Patel"
REASON = "Reopened for a repeat check"
ROOT = Path(__file__).resolve().parents[2]


def _make(client, owner: str | None = NURSE_NAME, **body) -> dict:
    payload = {"title": "On behalf task", **body}
    if owner is not None:
        payload["owner"] = owner
    response = client.post("/api/tasks", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _insert(status: str, assigned_to: str | None, tid: str) -> str:
    db = SessionLocal()
    try:
        db.add(
            Task(
                id=tid,
                patient_id="pat_ravi",
                encounter_id="enc_ipd_1",
                title="On behalf inserted task",
                status=status,
                priority="normal",
                owner=assigned_to,
                assigned_to=assigned_to,
                due_at=utcnow(),
                created_at=utcnow(),
            )
        )
        db.commit()
        return tid
    finally:
        db.close()


def _row(task_id: str) -> dict:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        return {
            "status": task.status,
            "assigned_to": task.assigned_to,
            "owner": task.owner,
            "acknowledged_by": task.acknowledged_by,
            "level": task.escalation_level or 0,
        }
    finally:
        db.close()


def _audit(task_id: str, action: str | None = None) -> list[AuditEntry]:
    db = SessionLocal()
    try:
        rows = list(db.scalars(select(AuditEntry).where(AuditEntry.entity_id == task_id).order_by(AuditEntry.created_at)))
        for row in rows:
            db.expunge(row)
        return [r for r in rows if action is None or r.action == action]
    finally:
        db.close()


def _ack(client, task_id: str, route: str):
    if route == "post":
        return client.post(f"/api/tasks/{task_id}/acknowledge")
    return client.patch(f"/api/tasks/{task_id}", json={"status": "acknowledged"})


def _on_behalf(entry: AuditEntry, who: str = NURSE_NAME) -> None:
    assert entry.actor_name == DOCTOR_NAME
    assert entry.meta["on_behalf_of"] == who
    assert entry.after["on_behalf_of"] == who


# ---------------- acknowledge ----------------

@pytest.mark.parametrize("route", ["post", "patch"])
def test_the_doctor_acknowledges_a_task_assigned_to_the_nurse(client, route):
    task = _make(client)
    response = _ack(client, task["id"], route)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "acknowledged"
    assert response.json()["acknowledged_by"] == NURSE_NAME
    row = _row(task["id"])
    assert row["acknowledged_by"] == NURSE_NAME
    assert row["assigned_to"] == NURSE_NAME and row["owner"] == NURSE_NAME
    entries = _audit(task["id"], "task_acknowledged")
    assert len(entries) == 1
    _on_behalf(entries[0])


def test_the_explicit_doctor_header_behaves_the_same(client):
    task = _make(client)
    response = client.post(f"/api/tasks/{task['id']}/acknowledge", headers={"X-User-Id": "u_meera"})
    assert response.status_code == 200
    assert response.json()["acknowledged_by"] == NURSE_NAME
    _on_behalf(_audit(task["id"], "task_acknowledged")[0])


def test_an_actor_in_the_body_is_ignored(client):
    task = _make(client)
    response = client.post(f"/api/tasks/{task['id']}/acknowledge", json={"actor": "Someone Else"})
    assert response.status_code == 200
    assert response.json()["acknowledged_by"] == NURSE_NAME
    entry = _audit(task["id"], "task_acknowledged")[0]
    assert entry.actor_name == DOCTOR_NAME


def test_the_assignee_name_is_data_for_any_name(client):
    task = _make(client)
    assert client.post(f"/api/tasks/{task['id']}/assign", json={"assigned_to": PHARMACIST_NAME}).status_code == 200
    response = client.post(f"/api/tasks/{task['id']}/acknowledge")
    assert response.status_code == 200
    assert response.json()["acknowledged_by"] == PHARMACIST_NAME
    _on_behalf(_audit(task["id"], "task_acknowledged")[0], PHARMACIST_NAME)


def test_a_task_assigned_to_the_doctor_is_not_on_behalf_of_anyone(client):
    task = _make(client, owner=DOCTOR_NAME)
    response = client.post(f"/api/tasks/{task['id']}/acknowledge")
    assert response.status_code == 200
    assert response.json()["acknowledged_by"] == DOCTOR_NAME
    entry = _audit(task["id"], "task_acknowledged")[0]
    assert entry.actor_name == DOCTOR_NAME
    assert "on_behalf_of" not in entry.meta and "on_behalf_of" not in entry.after
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"}).status_code == 200
    done = _audit(task["id"], "task_status_changed")[0]
    assert "on_behalf_of" not in done.meta and "on_behalf_of" not in done.after


# ---------------- complete and other status changes ----------------

def test_the_doctor_completes_a_task_for_the_nurse(client):
    task = _make(client)
    assert client.post(f"/api/tasks/{task['id']}/acknowledge").status_code == 200
    response = client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["acknowledged_by"] == NURSE_NAME
    row = _row(task["id"])
    assert row["assigned_to"] == NURSE_NAME and row["acknowledged_by"] == NURSE_NAME
    entry = _audit(task["id"], "task_status_changed")[0]
    _on_behalf(entry)
    assert entry.after["status"] == "completed"
    assert entry.after["completed_by"] == NURSE_NAME


@pytest.mark.parametrize("new_status", ["in_progress", "cancelled"])
def test_starting_or_cancelling_carries_on_behalf_of(client, new_status):
    task = _make(client)
    assert client.post(f"/api/tasks/{task['id']}/acknowledge").status_code == 200
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": new_status}).status_code == 200
    entry = _audit(task["id"], "task_status_changed")[0]
    _on_behalf(entry)
    assert "completed_by" not in entry.after


# ---------------- escalate and reopen ----------------

def test_the_doctor_escalates_for_the_nurse(client):
    task = _make(client)
    response = client.post(f"/api/tasks/{task['id']}/escalate", json={"reason": "Bed needed urgently"})
    assert response.status_code == 200, response.text
    assert response.json()["escalation_level"] == 1
    assert _row(task["id"])["assigned_to"] == NURSE_NAME
    entry = _audit(task["id"], "task_escalated")[0]
    _on_behalf(entry)
    assert entry.after["kind"] == "manual" and entry.after["escalation_level"] == 1


def test_the_doctor_reopens_a_completed_task_for_the_nurse(client):
    task = _make(client)
    tid = task["id"]
    assert client.post(f"/api/tasks/{tid}/acknowledge").status_code == 200
    assert client.patch(f"/api/tasks/{tid}", json={"status": "completed"}).status_code == 200
    response = client.post(f"/api/tasks/{tid}/reopen", json={"reason": REASON})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "accepted"
    assert body["acknowledged_by"] is None
    assert body["assigned_to"] == NURSE_NAME
    entry = _audit(tid, "task_reopened")[0]
    _on_behalf(entry)
    assert entry.meta["reason"] == REASON and entry.after["reason"] == REASON
    assert entry.before["acknowledged_by"] == NURSE_NAME


def test_the_whole_path_is_the_doctor_acting_and_the_nurse_named(client):
    tid = _make(client)["id"]
    assert client.post(f"/api/tasks/{tid}/acknowledge").status_code == 200
    assert client.patch(f"/api/tasks/{tid}", json={"status": "in_progress"}).status_code == 200
    assert client.patch(f"/api/tasks/{tid}", json={"status": "completed"}).status_code == 200
    assert client.post(f"/api/tasks/{tid}/reopen", json={"reason": REASON}).status_code == 200
    assert client.post(f"/api/tasks/{tid}/acknowledge").status_code == 200
    entries = _audit(tid)
    actions = [e.action for e in entries]
    assert actions[0] == "task_created"
    for action in ("task_acknowledged", "task_status_changed", "task_reopened"):
        assert action in actions
    for entry in entries:
        assert entry.actor_name == DOCTOR_NAME
        if entry.action != "task_created":
            assert entry.meta["on_behalf_of"] == NURSE_NAME
    assert _row(tid)["assigned_to"] == NURSE_NAME
    assert _row(tid)["acknowledged_by"] == NURSE_NAME


# ---------------- what still refuses ----------------

@pytest.mark.parametrize("route", ["post", "patch"])
def test_an_unassigned_task_is_still_a_400(client, route):
    tid = _insert("accepted", None, f"tsk_obo_unassigned_{route}")
    response = _ack(client, tid, route)
    assert response.status_code == 400, response.text
    assert "Assign" in response.json()["detail"]
    assert _row(tid)["status"] == "accepted" and _row(tid)["acknowledged_by"] is None


@pytest.mark.parametrize("status", ["proposed", "acknowledged", "in_progress", "completed", "cancelled"])
def test_acknowledging_from_the_wrong_state_is_still_a_409(client, status):
    tid = _insert(status, NURSE_NAME, f"tsk_obo_state_{status}")
    response = client.post(f"/api/tasks/{tid}/acknowledge")
    assert response.status_code == 409, response.text
    assert status in response.json()["detail"]
    assert _row(tid)["status"] == status
    assert _row(tid)["acknowledged_by"] is None
    assert _audit(tid, "task_acknowledged") == []


def test_other_bad_transitions_are_still_a_409(client):
    task = _make(client)
    refused = client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    assert refused.status_code == 409
    assert _row(task["id"])["status"] == "accepted"
    assert _audit(task["id"], "task_status_changed") == []
    not_closed = client.post(f"/api/tasks/{task['id']}/reopen", json={"reason": REASON})
    assert not_closed.status_code == 409


# ---------------- overdue escalation is the system's act ----------------

def test_overdue_escalation_is_still_the_engine_with_no_on_behalf_of(client):
    late = _make(client, due_in_hours=-9)["id"]
    response = client.post("/api/tasks/escalations/run")
    assert response.status_code == 200
    assert late in [t["id"] for t in response.json()["escalated"]]
    assert _row(late)["level"] == 2
    entries = _audit(late, "task_escalated")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actor_type == "system"
    assert entry.actor_name == "Escalation engine"
    assert entry.after["kind"] == "automatic"
    assert "on_behalf_of" not in entry.meta and "on_behalf_of" not in entry.after
    client.post("/api/tasks/escalations/run")
    assert len(_audit(late, "task_escalated")) == 1


# ---------------- F14 Open-record button (no frontend runner: static checks) ----------------

def _frontend(*parts: str) -> str:
    path = ROOT.joinpath("frontend", *parts)
    if not path.exists():
        pytest.skip(f"frontend source not present: {path}")
    return path.read_text()


def test_open_record_button_is_disabled_for_a_record_that_is_not_browsable():
    source = _frontend("src", "features", "f14", "OpenRecordButton.tsx")
    assert "browsable" in source
    assert "browsable?: boolean" in source and "browsable = true" in source
    assert "browsable === false" in source
    assert "disabled" in source and "title=" in source
    assert "session.setPatient(patientId)" in source  # the open path is unchanged
    assert source.index("browsable === false") < source.index("session.setPatient")


def test_the_dashboard_row_type_declares_browsable_as_optional():
    source = _frontend("src", "types.ts")
    block = source[source.index("export type HospitalDashboard"):]
    block = block[: block.index("claim: {")]
    assert "browsable?: boolean;" in block
