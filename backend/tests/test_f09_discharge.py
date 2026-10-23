"""F9 Discharge summary: assembled from documented events only, for doctor approval.

PRD: "Assembles the stay from documented events only, for doctor approval." Journey stage 4: "Open
tasks escalated." Rules 1 (a clinician decides) and 2 (never invent).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditEntry, Task, TimelineEvent

from .helpers import SHORT_VISIT, discharge, inject_event, inject_lab, texts

REASON = "Reviewed with the team before discharge"


def _generate(client) -> dict:
    response = client.post("/api/discharge/generate")
    assert response.status_code == 200, response.text
    return response.json()["draft"]


def _paragraphs(draft: dict, heading: str) -> list[dict]:
    for section in draft["content"]["sections"]:
        if section["heading"] == heading:
            return section["paragraphs"]
    return []


def _audit(action: str) -> list[AuditEntry]:
    db = SessionLocal()
    try:
        rows = db.scalars(select(AuditEntry).where(AuditEntry.action == action)).all()
        for row in rows:
            db.expunge(row)
        return list(rows)
    finally:
        db.close()


def _tasks() -> list[Task]:
    db = SessionLocal()
    try:
        rows = db.scalars(select(Task).where(Task.encounter_id == "enc_ipd_1")).all()
        for row in rows:
            db.expunge(row)
        return list(rows)
    finally:
        db.close()


def _events(type_name: str) -> list[TimelineEvent]:
    db = SessionLocal()
    try:
        rows = db.scalars(select(TimelineEvent).where(TimelineEvent.type == type_name)).all()
        for row in rows:
            db.expunge(row)
        return list(rows)
    finally:
        db.close()


def _claim(text: str) -> dict:
    return {"text": text, "source_event_ids": [], "source_segment_ids": ["seg_1"], "confidence": 0.9}


def _complete_record_without_warnings() -> None:
    """The five required documents on an otherwise empty record: no open alert, no open task."""
    for type_name in ("consult_note", "admission_note", "round_note", "procedure"):
        inject_event(type=type_name, title=type_name, payload={}, source="test")
    inject_lab("Creatinine", "1.1", "mg/dL", "0.7-1.3", "normal", datetime(2026, 10, 19, 6, 0))


# ---------- sections are quotes of approved notes ----------

def test_sections_are_verbatim_quotes_of_the_approved_notes(client):
    draft = _generate(client)
    diagnosis = _paragraphs(draft, "Admission diagnosis")
    assert [p["text"] for p in diagnosis] == [
        "Right lower leg cellulitis",
        "Type 2 diabetes",
        "CKD stage 3b",
    ]
    cellulitis = diagnosis[0]["source_event_ids"]
    assert set(cellulitis) == {"evt_seed_consult", "evt_seed_admission"}
    assert diagnosis[1]["source_event_ids"] == ["evt_seed_consult"]

    course = _paragraphs(draft, "Hospital course")
    assert [p["text"] for p in course] == [
        "Continue IV antibiotics and review the leg tomorrow.",
        "Check potassium and renal function.",
        "Hold metformin until renal function improves.",
    ]
    assert all(p["source_event_ids"] == ["evt_seed_round"] for p in course)

    procedures = _paragraphs(draft, "Procedures")
    assert [p["text"] for p in procedures] == [
        "Bedside wound debridement of right lower leg cellulitis performed by surgical team."
    ]
    assert procedures[0]["source_event_ids"] == ["evt_seed_procedure"]


def test_summary_contains_no_fixed_clinical_text(client):
    draft = _generate(client)
    text = " ".join(texts(draft["content"])).lower()
    for invented in ("in a patient with type 2 diabetes", "performed during the admission", "return urgently", "within one week"):
        assert invented not in text


def test_red_flags_are_never_generated_and_follow_up_is_empty_when_no_note_has_one(client):
    content = _generate(client)["content"]
    assert content["red_flags"] == []
    assert content["follow_up"] == []
    assert "Follow-up" in content["not_documented"]
    assert "Red flags / return advice" in content["not_documented"]


def test_investigations_come_from_the_latest_results_and_cite_them(client):
    draft = _generate(client)
    investigations = _paragraphs(draft, "Investigations")
    assert len(investigations) == 1
    text = investigations[0]["text"]
    assert text.startswith("Latest results: ") and "Creatinine" in text
    assert investigations[0]["source_event_ids"]
    assert all(event_id.startswith("evt_") for event_id in investigations[0]["source_event_ids"])


def test_a_new_result_reaches_the_discharge_investigations(client):
    inject_lab("eGFR", "18", "mL/min/1.73m²", "> 90", "low", datetime(2026, 10, 20, 10, 0))
    text = _paragraphs(_generate(client), "Investigations")[0]["text"]
    assert "eGFR 18 mL/min/1.73m²" in text


def test_pending_results_list_unreviewed_results_with_their_source(client):
    pending = _generate(client)["content"]["pending_results"]
    assert any("Creatinine remains unreviewed" in p["text"] and p["source_event_ids"] for p in pending)


def test_notes_approved_through_the_app_are_quoted_and_follow_up_is_only_what_notes_say(fresh):
    inject_event(
        type="consult_note",
        title="Consultation note",
        payload={
            "assessment": [_claim("Mild persistent asthma")],
            "plan": [_claim("Start salbutamol inhaler as needed"), _claim("Review in four weeks with a peak flow diary.")],
            "follow_up": _claim("Come back sooner if wheeze worsens."),
        },
        source="F1",
    )
    inject_event(
        type="progress_note",
        title="Progress note",
        payload={"assessment": [_claim("Improving on treatment")], "plan": _claim("Repeat peak flow in 2 weeks")},
        source="F4",
    )
    inject_event(type="round_note", title="Round", payload={"note_claims": [_claim("Chest clear on the round.")]}, source="F3")
    content = _generate(fresh)["content"]
    sections = {s["heading"]: [p["text"] for p in s["paragraphs"]] for s in content["sections"]}
    assert sections["Admission diagnosis"] == ["Mild persistent asthma", "Improving on treatment"]
    assert sections["Hospital course"] == ["Chest clear on the round."]
    follow_up = [p["text"] for p in content["follow_up"]]
    assert follow_up == [
        "Come back sooner if wheeze worsens.",
        "Review in four weeks with a peak flow diary.",
        "Repeat peak flow in 2 weeks",
    ]
    assert "Start salbutamol inhaler as needed" not in follow_up
    assert all(p["source_event_ids"] and p["source_event_ids"][0].startswith("evt_") for p in content["follow_up"])
    assert "Procedures" in content["not_documented"] and "Investigations" in content["not_documented"]
    assert "Follow-up" not in content["not_documented"]


def test_superseded_and_unapproved_notes_are_not_quoted(fresh):
    inject_event(type="consult_note", title="Old consult", status="superseded", payload={"assessment": ["Old diagnosis"]}, source="F1")
    inject_event(type="admission_note", title="Unsigned", status="draft", payload={"assessment": ["Unsigned diagnosis"]}, source="F2")
    inject_event(type="admission_note", title="Signed", payload={"assessment": ["Signed diagnosis"]}, source="F2")
    content = _generate(fresh)["content"]
    text = " ".join(texts(content))
    assert "Signed diagnosis" in text
    assert "Old diagnosis" not in text and "Unsigned diagnosis" not in text


def test_empty_record_gives_an_empty_summary_that_lists_what_is_missing(fresh):
    content = _generate(fresh)["content"]
    assert content["sections"] == []
    assert content["follow_up"] == [] and content["red_flags"] == [] and content["pending_results"] == []
    assert content["not_documented"] == [
        "Admission diagnosis",
        "Hospital course",
        "Procedures",
        "Investigations",
        "Follow-up",
        "Red flags / return advice",
    ]


# ---------- readiness ----------

def test_readiness_reports_items_warnings_and_ready(client):
    body = client.get("/api/discharge/readiness").json()
    assert [i["key"] for i in body["items"]] == ["consult_note", "admission_note", "round_note", "lab_result", "procedure"]
    assert all(i["present"] for i in body["items"])
    assert body["ready"] is True
    alerts = body["warnings"]["open_critical_alerts"]
    assert {a["title"] for a in alerts} >= {
        "Contradicting allergy documentation",
        "Metformin contraindicated at eGFR below 30",
    }
    assert all(set(a) == {"id", "title"} for a in alerts)
    tasks = {t["id"] for t in body["warnings"]["open_tasks"]}
    assert tasks == {"tsk_seed_metformin", "tsk_seed_potassium", "tsk_seed_followup"}
    assert "tsk_seed_antibiotics" not in tasks  # completed work is not open
    assert body["needs_override"] is True
    assert body["already_signed"] is False and body["encounter_status"] == "active"


def test_readiness_on_the_empty_record_is_not_ready(fresh):
    body = fresh.get("/api/discharge/readiness").json()
    assert body["ready"] is False
    assert not any(i["present"] for i in body["items"])
    assert body["warnings"] == {
        "open_critical_alerts": [],
        "open_tasks": [],
        "unresolved_medicine_differences": [],
    }
    assert body["needs_override"] is False


# ---------- approval rules ----------

def test_approval_without_override_is_409_and_names_the_alerts_and_tasks(client):
    response = discharge(client)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Contradicting allergy documentation" in detail
    assert "Interacting pair active: Warfarin + Ibuprofen" in detail
    assert "open tasks" in detail
    assert client.get("/api/discharge/readiness").json()["encounter_status"] == "active"
    assert _events("discharge_summary") == []


def test_a_short_reason_is_still_409(client):
    assert discharge(client, override={"reason": "ok fine"}).status_code == 409
    assert discharge(client, override={"reason": "   short   "}).status_code == 409
    assert discharge(client, override={}).status_code == 409
    assert _audit("discharge_override") == []
    assert client.get("/api/discharge/readiness").json()["encounter_status"] == "active"


def test_a_proper_reason_discharges_and_is_audited(client):
    response = discharge(client, override={"reason": f"  {REASON}  "})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["draft"]["status"] == "approved"
    assert body["event"]["type"] == "discharge_summary"
    assert client.get("/api/discharge/readiness").json()["encounter_status"] == "discharged"
    entries = _audit("discharge_override")
    assert len(entries) == 1
    assert entries[0].after["reason"] == REASON
    assert entries[0].entity_id == "enc_ipd_1"
    assert entries[0].actor_name == "Dr. Meera Shah"
    assert {a["title"] for a in entries[0].after["open_critical_alerts"]} >= {"Contradicting allergy documentation"}
    assert {t["id"] for t in entries[0].after["open_tasks"]} == {"tsk_seed_metformin", "tsk_seed_potassium", "tsk_seed_followup"}


def test_missing_documentation_blocks_even_with_a_proper_reason(client):
    db = SessionLocal()
    try:
        db.get(TimelineEvent, "evt_seed_procedure").status = "retracted"
        db.commit()
    finally:
        db.close()
    response = discharge(client, override={"reason": REASON})
    assert response.status_code == 409
    assert "Procedures documented" in response.json()["detail"]
    assert client.get("/api/discharge/readiness").json()["encounter_status"] == "active"
    assert _audit("discharge_override") == []


def test_a_record_with_no_warnings_needs_no_reason_and_writes_no_override_audit(fresh):
    _complete_record_without_warnings()
    assert fresh.get("/api/discharge/readiness").json()["needs_override"] is False
    response = discharge(fresh)
    assert response.status_code == 200, response.text
    assert _audit("discharge_override") == []


def test_open_tasks_are_escalated_at_discharge_with_the_reason(client):
    before = {t.id: (t.status, t.escalation_level or 0) for t in _tasks()}
    assert before["tsk_seed_metformin"][1] == 1 and before["tsk_seed_potassium"][1] == 0
    db = SessionLocal()
    try:
        db.get(Task, "tsk_seed_potassium").escalation_level = 2
        db.commit()
    finally:
        db.close()
    assert discharge(client, override={"reason": REASON}).status_code == 200
    after = {t.id: t for t in _tasks()}
    open_ids = {"tsk_seed_metformin", "tsk_seed_potassium", "tsk_seed_followup"}
    for task_id in open_ids:
        assert after[task_id].escalation_reason == "Open at discharge"
        assert after[task_id].escalated_at is not None
    assert after["tsk_seed_metformin"].escalation_level == 1  # at least 1, not raised again
    assert after["tsk_seed_potassium"].escalation_level == 2  # never lowered
    assert after["tsk_seed_followup"].escalation_level == 1
    assert after["tsk_seed_antibiotics"].escalation_reason != "Open at discharge"
    assert after["tsk_seed_antibiotics"].status == "completed"
    audited = {e.entity_id for e in _audit("task_escalated") if e.after.get("kind") == "discharge"}
    assert audited == open_ids


def test_generate_charges_five_credits_and_approval_does_not(client):
    start = client.get("/api/credits").json()["balance"]
    draft = _generate(client)
    after_generate = client.get("/api/credits").json()
    assert after_generate["balance"] == start - 5
    assert after_generate["ledger"][0]["operation"] == "discharge_summary"
    assert after_generate["ledger"][0]["feature"] == "F9"
    assert after_generate["ledger"][0]["units"] == 5
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={"override": {"reason": REASON}}).status_code == 200
    assert client.get("/api/credits").json()["balance"] == start - 5


def test_a_refused_approval_does_not_charge_again(client):
    draft = _generate(client)
    balance = client.get("/api/credits").json()["balance"]
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={}).status_code == 409
    assert client.get("/api/credits").json()["balance"] == balance


def test_approving_twice_is_idempotent(client):
    draft = _generate(client)
    path = f"/api/drafts/{draft['id']}/approve"
    first = client.post(path, json={"override": {"reason": REASON}})
    assert first.status_code == 200
    escalations = len(_audit("task_escalated"))
    second = client.post(path, json={})
    assert second.status_code == 200
    assert second.json()["event"]["id"] == first.json()["event"]["id"]
    assert len(_events("discharge_summary")) == 1
    assert len(_audit("discharge_override")) == 1
    assert len(_audit("task_escalated")) == escalations


def test_after_discharge_notes_are_409_and_claim_work_continues(client):
    assert discharge(client, override={"reason": REASON}).status_code == 200
    assert client.post("/api/notes/generate", json={"feature": "F4", "transcript": SHORT_VISIT}).status_code == 409
    assert client.post("/api/tasks", json={"title": "After discharge"}).status_code == 409
    assert client.post("/api/discharge/generate").status_code == 409
    assert client.post("/api/revenue/claim-prep/explain").status_code == 200


def test_a_refused_generation_after_discharge_is_not_charged(client):
    assert discharge(client, override={"reason": REASON}).status_code == 200
    balance = client.get("/api/credits").json()["balance"]
    assert client.post("/api/discharge/generate").status_code == 409
    assert client.get("/api/credits").json()["balance"] == balance

