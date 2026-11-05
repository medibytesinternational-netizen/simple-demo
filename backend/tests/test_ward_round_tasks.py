"""Ward-round tasking: the chief doctor hands tasks to a senior doctor or a nurse.

Covers role-based viewing, role-restricted work, the urgent button (head of the queue),
investigation categories and the chart entry written when a task is finished.
"""

from __future__ import annotations

CHIEF = {"X-User-Id": "u_meera"}
SENIOR = {"X-User-Id": "u_arjun"}
NURSE = {"X-User-Id": "u_anita"}


def _create(client, **body) -> dict:
    payload = {"title": "Ward round task", **body}
    response = client.post("/api/tasks", json=payload, headers=CHIEF)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(client, headers) -> list[str]:
    response = client.get("/api/tasks", headers=headers)
    assert response.status_code == 200, response.text
    return [task["id"] for task in response.json()["tasks"]]


def test_chief_assigns_tasks_with_role_category_and_priority(client):
    task = _create(client, title="CT head", owner="Dr. Arjun Rao", assignee_role="senior_doctor", category="ct", priority="urgent")
    assert task["assignee_role"] == "senior_doctor"
    assert task["category"] == "ct"
    assert task["priority"] == "urgent"


def test_role_is_inferred_from_the_assignee_name(client):
    assert _create(client, owner="Nurse Anita Rao")["assignee_role"] == "nurse"
    assert _create(client, owner="Dr. Arjun Rao")["assignee_role"] == "senior_doctor"


def test_each_role_sees_only_its_own_tasks_and_the_chief_sees_all(client):
    for_senior = _create(client, title="MRI spine", owner="Dr. Arjun Rao", category="mri")["id"]
    for_nurse = _create(client, title="Wound dressing", owner="Nurse Anita Rao")["id"]

    chief = _ids(client, CHIEF)
    senior = _ids(client, SENIOR)
    nurse = _ids(client, NURSE)
    assert {for_senior, for_nurse} <= set(chief)
    assert for_senior in senior and for_nurse not in senior
    assert for_nurse in nurse and for_senior not in nurse


def test_staff_cannot_work_another_roles_task(client):
    for_senior = _create(client, owner="Dr. Arjun Rao")["id"]
    refused = client.post(f"/api/tasks/{for_senior}/acknowledge", headers=NURSE)
    assert refused.status_code == 403


def test_staff_cannot_create_tasks_or_mark_them_urgent(client):
    assert client.post("/api/tasks", json={"title": "Self task"}, headers=NURSE).status_code == 403
    task = _create(client, owner="Nurse Anita Rao")["id"]
    assert client.post(f"/api/tasks/{task}/urgent", headers=NURSE).status_code == 403


def test_urgent_button_moves_a_task_to_the_head_of_the_queue(client):
    first = _create(client, title="Normal one", owner="Nurse Anita Rao")["id"]
    last = _create(client, title="Normal two", owner="Nurse Anita Rao", due_in_hours=72)["id"]
    response = client.post(f"/api/tasks/{last}/urgent", headers=CHIEF)
    assert response.status_code == 200, response.text
    assert response.json()["priority"] == "urgent"
    queue = _ids(client, CHIEF)
    assert queue[0] == last
    assert queue.index(last) < queue.index(first)


def test_finished_task_is_written_to_the_patient_chart(client):
    task = _create(client, title="Repeat potassium", owner="Nurse Anita Rao", category="lab")["id"]
    assert client.post(f"/api/tasks/{task}/acknowledge", headers=NURSE).status_code == 200
    done = client.patch(f"/api/tasks/{task}", json={"status": "completed"}, headers=NURSE)
    assert done.status_code == 200, done.text
    event_id = done.json()["completion_event_id"]
    assert event_id

    timeline = client.get("/api/patients/pat_ravi/timeline", headers=CHIEF).json()["events"]
    event = next(item for item in timeline if item["id"] == event_id)
    assert event["type"] == "task_completed"
    assert "Lab report" in event["title"]
    assert event["author_name"] == "Nurse Anita Rao"
