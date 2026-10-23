"""F3 Interdisciplinary handover: one verified round instruction becomes the note, the nursing chart
and the task board.

PRD rules 1, 2 and 4: nothing is written that nobody said, every line cites its segment, and a
discussion or a task is not an order or a completion.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.db import utcnow
from app.services.cached.f03_round import NO_INSTRUCTIONS, f3_round
from app.services.context import segments_from_transcript

from .helpers import generate_note

DOCTOR_NAME = "Dr. Meera Shah"

ROUND = (
    "Doctor: Good morning, how is the leg?\n"
    "Patient: It hurts less than yesterday.\n"
    "Doctor: The right leg is less red and temperature is 37.2.\n"
    "Doctor: This looks like cellulitis that is improving.\n"
    "Doctor: Continue IV flucloxacillin and review the leg tomorrow.\n"
    "Nurse: Understood, I will hold metformin.\n"
    "Nurse: Is the potassium result back?\n"
    "Nurse: The dressing was dry this morning.\n"
    "Doctor: Stop metformin until renal function improves. Check potassium this morning."
)

DECLINED = (
    "Doctor: Her knee pain is settled.\n"
    "Doctor: She asked about stronger tablets but we will keep the current dose.\n"
    "Doctor: Book a physiotherapy review for Friday."
)

NO_PLAN = "Doctor: How are you feeling today?\nPatient: Much better, thank you.\nDoctor: Good."


def _transcript_text(transcript: str) -> str:
    return "\n".join(line.split(":", 1)[1].strip() for line in transcript.splitlines())


def _task_count(client) -> int:
    return len(client.get("/api/tasks").json()["tasks"])


def _nursing_chart_events(client) -> list[dict]:
    events = client.get("/api/patients/pat_ravi/timeline").json()["events"]
    return [e for e in events if e["type"] == "nursing_chart"]


@pytest.mark.parametrize("transcript", [ROUND, DECLINED])
def test_note_claims_and_nursing_entries_are_verbatim_and_cited(client, transcript):
    draft = generate_note(client, "F3", transcript)
    content = draft["content"]
    spoken = _transcript_text(transcript)
    segments = {s["segment_id"]: s["text"] for s in segments_from_transcript(transcript)}
    transcript_event = draft["created_from_event_ids"][0]
    claims = content["note_claims"] + content["nursing_entries"]
    assert claims
    for item in claims:
        assert item["text"] in spoken
        assert item["source_event_ids"] == [transcript_event]
        assert item["source_segment_ids"]
        assert all(item["text"] in segments[seg] for seg in item["source_segment_ids"])
    said = spoken.lower()
    for word in ("ibuprofen", "ckd", "warfarin"):
        if word not in said:
            assert all(word not in item["text"].lower() for item in claims)


def test_note_claims_are_clinician_exam_assessment_and_plan_in_order_said(client):
    texts = [c["text"] for c in generate_note(client, "F3", ROUND)["content"]["note_claims"]]
    assert texts == [
        "The right leg is less red and temperature is 37.2.",
        "This looks like cellulitis that is improving.",
        "Continue IV flucloxacillin and review the leg tomorrow.",
        "Stop metformin until renal function improves.",
        "Check potassium this morning.",
    ]


def test_nursing_entries_are_plan_instructions_and_the_nurses_own_acknowledgement(client):
    content = generate_note(client, "F3", ROUND)["content"]
    assert [e["text"] for e in content["nursing_entries"]] == [
        "Continue IV flucloxacillin and review the leg tomorrow.",
        "Understood, I will hold metformin.",
        "Stop metformin until renal function improves.",
        "Check potassium this morning.",
    ]
    task_titles = " ".join(t["title"] for t in content["proposed_tasks"])
    assert "Understood" not in task_titles
    assert len(content["proposed_tasks"]) == 3


LONG = "Continue " + "intravenous flucloxacillin every six hours " * 4 + "and review the leg tomorrow."


@pytest.mark.parametrize(
    "sentence, priority, hours",
    [
        ("Stop the aspirin.", "urgent", 8),
        ("Hold the evening dose.", "urgent", 8),
        ("Check the blood sugar.", "urgent", 8),
        ("Give the potassium supplement.", "urgent", 8),
        ("Repeat the renal profile on Friday.", "urgent", 8),
        ("Continue the antibiotics.", "routine", 24),
        ("Book a physiotherapy review.", "routine", 24),
        (LONG, "routine", 24),
    ],
)
def test_proposed_task_priority_due_time_and_wording(client, sentence, priority, hours):
    transcript = f"Doctor: Round review.\nDoctor: {sentence}"
    task = generate_note(client, "F3", transcript)["content"]["proposed_tasks"][0]
    assert task["priority"] == priority
    assert task["due_in_hours"] == hours
    assert task["confidence"] == 0.6
    assert task["source_segment_ids"] == ["seg_2"]
    assert task["title"] == sentence.rstrip(".")[:110]
    assert len(task["title"]) <= 110
    assert sentence in task["detail"]


def test_transcript_without_instructions_gives_no_tasks_and_says_so(client):
    content = generate_note(client, "F3", NO_PLAN)["content"]
    assert content["proposed_tasks"] == []
    assert content["nursing_entries"] == []
    assert NO_INSTRUCTIONS in content["not_documented"]


def test_generating_creates_no_tasks_and_only_the_transcript_event(client):
    tasks_before = _task_count(client)
    before = client.get("/api/patients/pat_ravi/timeline").json()
    draft = generate_note(client, "F3", ROUND)
    assert draft["content"]["proposed_tasks"]
    after = client.get("/api/patients/pat_ravi/timeline").json()
    assert after["count"] == before["count"] + 1
    known = {e["id"] for e in before["events"]}
    assert [e["type"] for e in after["events"] if e["id"] not in known] == ["transcript"]
    assert _task_count(client) == tasks_before


def test_approving_writes_nursing_chart_entries_as_quoted_instructions(client):
    draft = generate_note(client, "F3", ROUND)
    quoted = [e["text"] for e in draft["content"]["nursing_entries"]]
    assert _nursing_chart_events(client) == []
    response = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert response.status_code == 200, response.text
    (chart,) = _nursing_chart_events(client)
    entries = chart["payload"]["entries"]
    assert [e["text"] for e in entries] == quoted
    assert all(e["kind"] == "instruction" for e in entries)
    assert chart["body_text"] == "\n".join(quoted)
    assert [e["text"] for e in entries if e.get("said_by") == "nurse"] == ["Understood, I will hold metformin."]
    assert entries[0]["source_segment_ids"] == draft["content"]["nursing_entries"][0]["source_segment_ids"]
    assert chart["payload"]["round_event_id"] == response.json()["event"]["id"]


def test_accepting_tasks_creates_exactly_the_chosen_ones_for_the_acting_user(client):
    draft = generate_note(client, "F3", ROUND)
    proposed = draft["content"]["proposed_tasks"]
    assert len(proposed) == 3
    before = _task_count(client)
    response = client.post(
        f"/api/drafts/{draft['id']}/accept-tasks", json={"indices": [1, 2], "actor": "Somebody Else"}
    )
    assert response.status_code == 200, response.text
    created = response.json()["tasks"]
    assert [t["title"] for t in created] == [proposed[1]["title"], proposed[2]["title"]]
    assert {t["status"] for t in created} == {"accepted"}
    assert {t["owner"] for t in created} == {DOCTOR_NAME}
    assert [t["priority"] for t in created] == ["urgent", "urgent"]
    board = client.get("/api/tasks").json()["tasks"]
    assert len(board) == before + 2
    from_draft = [t for t in board if t["accepted_from_draft_id"] == draft["id"]]
    assert [t["title"] for t in from_draft] == [c["title"] for c in created]
    again = client.post(f"/api/drafts/{draft['id']}/accept-tasks", json={"indices": [1, 2]})
    assert again.json()["tasks"] == []
    assert _task_count(client) == before + 2


def test_accepted_task_is_due_after_the_proposed_hours(client):
    draft = generate_note(client, "F3", "Doctor: Stop the aspirin.\nDoctor: Continue the antibiotics.")
    created = client.post(f"/api/drafts/{draft['id']}/accept-tasks", json={"indices": [0, 1]}).json()["tasks"]
    now = utcnow()
    from datetime import datetime

    due = [datetime.fromisoformat(t["due_at"]) for t in created]
    assert abs(due[0] - (now + timedelta(hours=8))) < timedelta(minutes=5)
    assert abs(due[1] - (now + timedelta(hours=24))) < timedelta(minutes=5)


def test_round_generator_with_no_transcript_reports_nothing_documented():
    content = f3_round({})
    assert content["note_claims"] == []
    assert content["nursing_entries"] == []
    assert content["proposed_tasks"] == []
    assert NO_INSTRUCTIONS in content["not_documented"]
    assert len(content["not_documented"]) == 2
