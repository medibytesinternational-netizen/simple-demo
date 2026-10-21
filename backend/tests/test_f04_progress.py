"""F4 daily progress note: drafted from what changed since the last note (PRD rules 2 and 3)."""

from __future__ import annotations

from datetime import datetime

from .helpers import SHORT_VISIT, generate_note, inject_event, inject_lab

SEED_PROGRESS_NOTE = "evt_seed_progress"
SEED_PROGRESS_TITLE = "Daily progress note — day 2"

ROUND_TRANSCRIPT = (
    "Patient: My leg pain is much less and I slept badly.\n"
    "Doctor: Your creatinine is still high. This looks like improving cellulitis.\n"
    "Doctor: Continue the antibiotics."
)


def _objective_text(draft: dict) -> str:
    return (draft["content"]["objective"] or {}).get("text", "")


def _inject_note(title: str, at: datetime) -> str:
    return inject_event(
        type="round_note",
        title=title,
        payload={"summary": "test round"},
        source="test_feed",
        author_type="human",
        author_name="Test",
        occurred_at=at,
    )


def _inject_order(drug: str, status: str, kind: str, at: datetime) -> str:
    return inject_event(
        type="med_order",
        title=f"Order — {drug}",
        payload={"drug": drug, "dose": "5 mg", "frequency": "OD", "kind": kind, "status": status},
        source="test_feed",
        author_type="human",
        author_name="Test",
        occurred_at=at,
    )


def test_progress_objective_names_a_newer_lab_and_cites_its_event(client):
    lab_id = inject_lab("eGFR", "18", "mL/min/1.73m²", "> 90", "low", datetime(2026, 10, 20, 10, 0))
    draft = generate_note(client, "F4", SHORT_VISIT)
    objective = draft["content"]["objective"]
    assert "eGFR 18 mL/min/1.73m² (low)" in objective["text"]
    assert lab_id in objective["source_event_ids"]
    assert lab_id in draft["evidence_event_ids"]


def test_vitals_since_the_last_note_are_in_the_objective_with_their_event(client):
    draft = generate_note(client, "F4", SHORT_VISIT)
    objective = draft["content"]["objective"]
    assert "temperature 37.4°C" in objective["text"]
    assert "evt_seed_vitals" in objective["source_event_ids"]


def test_lab_older_than_the_previous_note_is_not_reported_as_new(client):
    old_id = inject_lab("Sodium", "131", "mmol/L", "135 - 145", "low", datetime(2026, 10, 19, 9, 0))
    draft = generate_note(client, "F4", SHORT_VISIT)
    objective = draft["content"]["objective"]
    assert "sodium" not in objective["text"].lower()
    assert old_id not in objective["source_event_ids"]
    # the seeded labs were all taken before the note too
    # (a new alert may still cite an older lab as its own evidence; the lab is not reported as a result)
    assert "creatinine 2.9" not in objective["text"].lower()


def test_nothing_changed_gives_the_no_new_results_claim(client):
    note_id = _inject_note("Ward round — day 3", datetime(2030, 1, 1, 8, 0))
    objective = generate_note(client, "F4", SHORT_VISIT)["content"]["objective"]
    assert objective["text"] == "No new results, observations or orders since Ward round — day 3"
    assert objective["source_event_ids"] == [note_id]


def test_no_data_at_all_gives_no_objective(fresh):
    content = generate_note(fresh, "F4", SHORT_VISIT)["content"]
    assert content["objective"] is None
    assert "Objective" in content["not_documented"]


def test_new_order_and_stop_are_reported_but_home_medicines_are_not(client):
    started = _inject_order("Ceftriaxone", "active", "inpatient", datetime(2026, 10, 20, 8, 0))
    stopped = _inject_order("Heparin", "stopped", "inpatient", datetime(2026, 10, 20, 8, 30))
    home = _inject_order("Zolpidem", "active", "home", datetime(2026, 10, 20, 9, 0))
    objective = generate_note(client, "F4", SHORT_VISIT)["content"]["objective"]
    assert "Ceftriaxone 5 mg OD started" in objective["text"]
    assert "Heparin 5 mg OD stopped" in objective["text"]
    assert started in objective["source_event_ids"] and stopped in objective["source_event_ids"]
    assert "zolpidem" not in objective["text"].lower()
    assert home not in objective["source_event_ids"]


def test_subjective_and_assessment_quote_the_transcript(client):
    draft = generate_note(client, "F4", ROUND_TRANSCRIPT)
    content = draft["content"]
    assert content["subjective"]["text"] == "My leg pain is much less and I slept badly."
    assert content["subjective"]["source_segment_ids"] == ["seg_1"]
    assessment = [claim["text"] for claim in content["assessment"]]
    assert assessment == ["This looks like improving cellulitis."]
    assert content["assessment"][0]["source_segment_ids"] == ["seg_2"]
    # nothing the clinician did not say
    assert "no new breathlessness" not in str(content).lower()


def test_no_assessment_or_subjective_is_listed_when_nobody_said_any(fresh):
    content = generate_note(fresh, "F4", "Doctor: progress review.")["content"]
    assert content["subjective"] is None
    assert content["assessment"] == []
    assert {"Subjective", "Assessment"} <= set(content["not_documented"])


def test_exam_and_plan_are_empty_and_listed_as_not_documented(client):
    content = generate_note(client, "F4", SHORT_VISIT)["content"]
    assert content["exam"] == {"general": None, "systemic": None}
    assert content["plan"] is None
    assert content["not_documented"][:2] == ["Examination", "Plan"]


def test_context_names_previous_note_and_what_came_after(client):
    from app.db import SessionLocal
    from app.routes.common import _state
    from app.services.context import build_context

    db = SessionLocal()
    try:
        patient, encounter, state = _state(db)
        context = build_context(db, patient, encounter, state, "F4")
        other = build_context(db, patient, encounter, state, "F3")
    finally:
        db.close()
    assert context["previous_note"]["event_id"] == SEED_PROGRESS_NOTE
    assert context["previous_note"]["type"] == "progress_note"
    assert context["previous_note"]["title"] == SEED_PROGRESS_TITLE
    ids = [event["event_id"] for event in context["since_last"]["events"]]
    assert "evt_seed_vitals" in ids
    assert "evt_seed_lab_egfr" not in ids
    assert "previous_note" not in other and "since_last" not in other


def test_context_without_a_previous_note_holds_everything(fresh):
    from app.db import SessionLocal
    from app.routes.common import _state
    from app.services.context import build_context

    lab_id = inject_lab("eGFR", "40", "mL/min/1.73m²", "> 90", "low", datetime(2026, 10, 20, 10, 0))
    db = SessionLocal()
    try:
        patient, encounter, state = _state(db)
        context = build_context(db, patient, encounter, state, "F4")
    finally:
        db.close()
    assert context["previous_note"] is None
    assert [event["event_id"] for event in context["since_last"]["events"]] == [lab_id]


def test_progress_note_needs_clinician_exam_and_plan(client):  # guard
    draft = generate_note(client, "F4", SHORT_VISIT)
    response = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert response.status_code == 400
    assert "examination and plan" in response.text


def _clinician_text(text: str, human: bool = True) -> dict:
    return {
        "text": text,
        "source_event_ids": [],
        "source_segment_ids": [],
        "confidence": 1,
        "human_authored": human,
    }


def test_progress_note_signs_after_the_clinician_writes_exam_and_plan(client):
    draft = generate_note(client, "F4", SHORT_VISIT)
    content = draft["content"]
    content["exam"]["general"] = _clinician_text("Right leg less red, calf soft.")
    content["plan"] = _clinician_text("Continue antibiotics, repeat bloods tomorrow.")
    patched = client.patch(f"/api/drafts/{draft['id']}", json={"content": content})
    assert patched.status_code == 200, patched.text
    approved = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert approved.status_code == 200, approved.text
    signed = approved.json()["draft"]["content"]
    assert signed["exam"]["general"]["human_authored"] is True
    assert signed["plan"]["human_authored"] is True
    assert signed["exam"]["general"]["text"] == "Right leg less red, calf soft."
    assert approved.json()["event"]["type"] == "progress_note"


def test_generated_exam_and_plan_text_cannot_be_signed_as_the_clinicians(client):
    draft = generate_note(client, "F4", SHORT_VISIT)
    content = draft["content"]
    content["exam"]["general"] = _clinician_text("Right leg less red.", human=False)
    content["plan"] = _clinician_text("Continue antibiotics.", human=False)
    assert client.patch(f"/api/drafts/{draft['id']}", json={"content": content}).status_code == 200
    response = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert response.status_code == 400
    assert "written by the clinician" in response.text
