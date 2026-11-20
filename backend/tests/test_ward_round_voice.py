"""Ward round: the senior doctor dictates or uploads a round per patient; the work said on the
round is split between the junior doctor and the nurse, timed, reviewed, then assigned.
Each role sees only its own tasks, across every patient on the ward."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.db import utcnow
from app.services import round_tasks

from .helpers import FakePipeline
from .test_f02_admission import _new_patient_with_opd
from .test_voice_upload import _consent, _wav

CHIEF = {"X-User-Id": "u_meera"}
SENIOR = {"X-User-Id": "u_arjun"}
JUNIOR = {"X-User-Id": "u_kiran"}
NURSE = {"X-User-Id": "u_anita"}

ROUND = (
    "Doctor: Abdomen is soft, mildly tender in the right iliac fossa.\n"
    "Doctor: Impression is resolving appendicitis.\n"
    "Doctor: Check vitals every four hours and record intake and output.\n"
    "Doctor: Repeat serum creatinine in 6 hours.\n"
    "Doctor: Start IV ceftriaxone 1 g twice daily.\n"
)


def _round(client, headers=SENIOR, extra: dict | None = None) -> dict:
    response = client.post("/api/notes/generate", json={"feature": "F3", "transcript": ROUND},
                           headers={**headers, **(extra or {})})
    assert response.status_code == 200, response.text
    return response.json()["draft"]


def _approved_round(client, headers=SENIOR, extra: dict | None = None) -> dict:
    """A round whose report is approved, so its tasks can be assigned."""
    draft = _round(client, headers, extra)
    response = client.post(f"/api/drafts/{draft['id']}/approve", json={}, headers={**headers, **(extra or {})})
    assert response.status_code == 200, response.text
    return draft


@pytest.mark.parametrize(
    "said, role",
    [
        ("Check vitals every four hours.", "nurse"),
        ("Give paracetamol 1 g now.", "nurse"),
        ("Nurse, please do the wound dressing.", "nurse"),
        ("Repeat serum creatinine in the morning.", "junior_doctor"),
        ("Start IV ceftriaxone.", "junior_doctor"),
        ("Dr. Kiran, chart the fluids.", "junior_doctor"),
    ],
)
def test_the_work_is_split_between_the_junior_doctor_and_the_nurse(said, role):
    assert round_tasks.assignee_role(said) == role


@pytest.mark.parametrize(
    "said, urgent, hours",
    [
        ("Repeat creatinine in 6 hours.", False, 6),
        ("Give the dose stat.", False, 1),
        ("Review in two hours.", False, 2),
        ("Review the leg tomorrow.", False, 24),
        ("Continue the antibiotics.", False, 24),
        ("Hold the metformin.", True, 8),
    ],
)
def test_a_time_said_on_the_round_sets_when_the_task_is_due(said, urgent, hours):
    assert round_tasks.due_in_hours(said, urgent) == hours


def test_by_a_clock_time_counts_forward_to_that_time():
    now = datetime(2026, 11, 17, 10, 0)
    assert round_tasks.due_in_hours("Send the sample by 6 pm.", False, now) == 8


def test_a_senior_doctor_runs_the_round_and_the_tasks_carry_role_category_and_time(client):
    tasks = _round(client)["content"]["proposed_tasks"]
    by_title = {t["title"]: t for t in tasks}
    vitals = next(t for title, t in by_title.items() if "vitals" in title.lower())
    creatinine = next(t for title, t in by_title.items() if "creatinine" in title.lower())
    assert vitals["assignee_role"] == "nurse"
    assert creatinine["assignee_role"] == "junior_doctor"
    assert creatinine["category"] == "lab" and creatinine["due_in_hours"] == 6


def test_juniors_and_nurses_may_not_run_the_round_or_assign_its_tasks(client):
    draft = _round(client)
    for who in (JUNIOR, NURSE):
        refused = client.post("/api/notes/generate", json={"feature": "F3", "transcript": ROUND}, headers=who)
        assert refused.status_code == 403
        assert client.post(f"/api/drafts/{draft['id']}/accept-tasks", json={"indices": [0]}, headers=who).status_code == 403


def test_a_senior_doctor_still_may_not_draft_other_notes(client):
    response = client.post("/api/notes/generate", json={"feature": "F1", "transcript": "Doctor: Cough for two days."}, headers=SENIOR)
    assert response.status_code == 403


def test_the_reviewed_tasks_are_assigned_with_the_edits_and_unticked_ones_are_left_out(client):
    draft = _approved_round(client)
    proposed = draft["content"]["proposed_tasks"]
    assert len(proposed) >= 3
    # Keep tasks 0 and 1; move task 0 to the junior doctor, make task 1 urgent within 2 hours.
    body = {"tasks": [
        {"index": 0, "assignee_role": "junior_doctor"},
        {"index": 1, "priority": "urgent", "due_in_hours": 2, "title": "Repeat creatinine (edited)"},
    ]}
    response = client.post(f"/api/drafts/{draft['id']}/accept-tasks", json=body, headers=SENIOR)
    assert response.status_code == 200, response.text
    created = response.json()["tasks"]
    assert len(created) == 2
    first, second = created
    assert first["assignee_role"] == "junior_doctor" and first["assigned_to"] == "Dr. Kiran Patel"
    assert second["title"] == "Repeat creatinine (edited)" and second["priority"] == "urgent"
    assert second["assignee_role"] == proposed[1]["assignee_role"]
    due = datetime.fromisoformat(second["due_at"])
    assert abs(due - (utcnow() + timedelta(hours=2))) < timedelta(minutes=5)


def test_each_role_sees_only_its_own_round_tasks_across_patients(client):
    # Round on the default patient.
    draft = _approved_round(client)
    proposed = draft["content"]["proposed_tasks"]
    client.post(f"/api/drafts/{draft['id']}/accept-tasks",
                json={"tasks": [{"index": i} for i in range(len(proposed))]}, headers=SENIOR)
    # Round on a second patient.
    other = _new_patient_with_opd(client, name="Lakshmi Iyer")
    draft2 = _approved_round(client, extra={"X-Patient-Id": other})
    client.post(f"/api/drafts/{draft2['id']}/accept-tasks",
                json={"tasks": [{"index": i} for i in range(len(draft2["content"]["proposed_tasks"]))]},
                headers={**SENIOR, "X-Patient-Id": other})

    def mine(headers):
        response = client.get("/api/tasks?scope=mine", headers=headers)
        assert response.status_code == 200, response.text
        return [t for t in response.json()["tasks"] if t["accepted_from_draft_id"] in (draft["id"], draft2["id"])]

    junior, nurse = mine(JUNIOR), mine(NURSE)
    assert junior and nurse
    assert {t["assignee_role"] for t in junior} == {"junior_doctor"}
    assert {t["assignee_role"] for t in nurse} == {"nurse"}
    assert {t["patient_id"] for t in junior} == {"pat_ravi", other}
    assert all(t["patient_name"] for t in junior)
    # The senior doctor sees what they assigned; the junior cannot work a nurse task.
    assert len(mine(SENIOR)) == len(junior) + len(nurse)
    nurse_task = nurse[0]
    refused = client.patch(f"/api/tasks/{nurse_task['id']}", json={"status": "in_progress"},
                           headers={**JUNIOR, "X-Patient-Id": nurse_task["patient_id"]})
    assert refused.status_code == 403


def test_a_round_recording_becomes_a_round_draft_with_role_tagged_tasks_and_is_not_approved(fresh, monkeypatch):
    fake = FakePipeline().install(monkeypatch)
    fake.transcript = ROUND.replace("Doctor: ", "")
    _consent(fresh)
    submitted = fresh.post("/api/notes/transcribe", data={"feature": "F3"},
                           files={"file": ("round.wav", _wav(), "audio/wav")}, headers=SENIOR)
    assert submitted.status_code == 200, submitted.text
    assert fake.feature == "F3"
    polled = fresh.get(f"/api/notes/transcribe/{submitted.json()['audio_id']}", headers=SENIOR).json()
    assert polled["status"] == "succeeded", polled
    draft = polled["draft"]
    assert draft["feature"] == "F3" and draft["status"] != "approved"
    roles = {t["assignee_role"] for t in draft["content"]["proposed_tasks"]}
    assert roles == {"junior_doctor", "nurse"}
