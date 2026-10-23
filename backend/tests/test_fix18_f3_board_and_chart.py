"""Fixes for the F3 round: the task board, the nursing-chart authorship and the nurse backfill.

PRD rules 2 and 4: nothing is written that nobody said, and a task is not a completion.
"""

from __future__ import annotations

from app.db import SessionLocal
from app.services import llm
from app.services.cached.f03_round import NO_INSTRUCTIONS
from app.services.context import segments_from_transcript

from .helpers import generate_note

DOCTOR_NAME = "Dr. Meera Shah"

ROUND = (
    "Doctor: The right leg is less red.\n"
    "Doctor: Stop metformin until renal function improves.\n"
    "Doctor: Check potassium this morning."
)
QUESTION_AND_OBSERVATION = (
    "Doctor: Good morning.\n"
    "Nurse: Is the potassium result back?\n"
    "Nurse: The dressing was dry this morning."
)


def _open_task_ids(client) -> set[str]:
    readiness = client.get("/api/discharge/readiness").json()
    return {t["id"] for t in readiness["warnings"]["open_tasks"]}


def test_accepted_round_tasks_can_be_worked_to_completion_by_the_doctor_for_the_assignee(client):
    draft = generate_note(client, "F3", ROUND)
    response = client.post(f"/api/drafts/{draft['id']}/accept-tasks", json={"indices": [0, 1]})
    assert response.status_code == 200, response.text
    created = response.json()["tasks"]
    assert len(created) == 2
    for task in created:
        assert task["owner"] == DOCTOR_NAME
        assert task["assigned_to"] == DOCTOR_NAME
    ids = {t["id"] for t in created}
    assert ids <= _open_task_ids(client)

    for task in created:
        task_id = task["id"]
        assert client.post(f"/api/tasks/{task_id}/acknowledge").status_code == 200
        assert client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"}).status_code == 200
        done = client.patch(f"/api/tasks/{task_id}", json={"status": "completed"})
        assert done.status_code == 200, done.text
    assert not (ids & _open_task_ids(client))
    board = {t["id"]: t["status"] for t in client.get("/api/tasks").json()["tasks"]}
    assert {board[i] for i in ids} == {"completed"}


def test_nursing_chart_event_names_the_model_as_author_and_the_clinician_as_approver(client):
    draft = generate_note(client, "F3", ROUND)
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={}).status_code == 200
    events = client.get("/api/patients/pat_ravi/timeline").json()["events"]
    (chart,) = [e for e in events if e["type"] == "nursing_chart"]
    author = f"{draft['model']} ({draft['prompt_version']})"
    assert chart["author_name"] == author
    assert chart["author_name"] != DOCTOR_NAME
    assert chart["approved_by"] == DOCTOR_NAME
    assert chart["authorship"] == f"Drafted by {author}, approved by {DOCTOR_NAME}"
    assert chart["drafted_by"] == author
    assert chart["recorded_by"] == DOCTOR_NAME


def test_nurse_question_and_observation_are_not_chart_entries(client):
    draft = generate_note(client, "F3", QUESTION_AND_OBSERVATION)
    content = draft["content"]
    assert content["nursing_entries"] == []
    assert NO_INSTRUCTIONS in content["not_documented"]
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={}).status_code == 200
    events = client.get("/api/patients/pat_ravi/timeline").json()["events"]
    assert [e for e in events if e["type"] == "nursing_chart"] == []


def _force_backfill(monkeypatch, transcript: str) -> list[dict]:
    """Run the generator as if the model returned no nursing entries."""
    monkeypatch.setattr(
        llm,
        "cached_draft",
        lambda feature, context: {
            "note_claims": [], "nursing_entries": [], "proposed_tasks": [], "not_documented": [],
        },
    )
    segments = segments_from_transcript(transcript)
    context = {"transcript": {"event_id": "evt_round", "segments": segments}, "evidence_events": []}
    db = SessionLocal()
    try:
        content, _ = llm.generate_draft(db, "F3", context)
        db.rollback()
    finally:
        db.close()
    return content["nursing_entries"]


def test_backfill_keeps_only_the_nurses_acknowledgements(monkeypatch):
    transcript = QUESTION_AND_OBSERVATION + "\nNurse: Understood, I will hold metformin."
    entries = _force_backfill(monkeypatch, transcript)
    assert [e["text"] for e in entries] == ["Understood, I will hold metformin."]
    assert entries[0]["source_event_ids"] == ["evt_round"]
    assert entries[0]["source_segment_ids"] == ["seg_4"]


def test_backfill_with_no_acknowledgement_gives_no_entries(monkeypatch):
    assert _force_backfill(monkeypatch, QUESTION_AND_OBSERVATION) == []
