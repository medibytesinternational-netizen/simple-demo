"""Regression tests taken from the PRD review.

Tests marked "guard" protect behaviour that already matches the PRD.
The rest fail on the original code and pass once the matching fix lands.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .helpers import ASTHMA, SHORT_VISIT, discharge, generate_note, inject_event, inject_lab, joined, text_pdf


# ---------- Rule: never invent (F1, F2, F4, F9, F11) ----------

def test_consult_note_reflects_the_transcript(client):
    draft = generate_note(client, "F1", ASTHMA)
    text = joined(draft["content"])
    assert "wheeze" in text
    assert "cellulitis" not in text and "metformin" not in text


def test_consult_note_quotes_only_what_was_said(client):
    draft = generate_note(client, "F1", ASTHMA)
    said = ASTHMA.lower()
    quoted = [line for line in joined(draft["content"]).split(" ") if line]
    assert quoted, "an asthma conversation must produce some text"
    for claim in _claims(draft["content"]):
        assert claim["text"].lower().rstrip(".") in said, claim["text"]


def test_empty_record_drafts_invent_no_history(fresh):
    for feature in ("F2", "F4"):
        text = joined(generate_note(fresh, feature, SHORT_VISIT)["content"])
        for invented in ("cellulitis", "right leg", "58-year-old", "egfr", "metformin", "flucloxacillin"):
            assert invented not in text, f"{feature} invented {invented!r}"


def test_referral_needs_a_reason_on_an_empty_record(fresh):
    response = fresh.post("/api/referrals/generate", json={})
    if response.status_code == 200:
        text = joined(response.json()["draft"]["content"])
        assert "58-year-old" not in text and "egfr 22" not in text
    else:
        assert response.status_code == 422


def test_discharge_summary_invents_no_follow_up(client):
    content = client.post("/api/discharge/generate").json()["draft"]["content"]
    text = joined({"f": content["follow_up"], "r": content["red_flags"]})
    assert "within one week" not in text
    assert "return urgently" not in text


# ---------- Investigation form (F10) ----------

def test_investigation_form_generates_for_the_demo_patient(client):
    response = client.post("/api/investigation-requests/generate")
    assert response.status_code == 200, response.text


def test_investigation_form_blocks_approval_until_allergy_verified(client):
    draft = client.post("/api/investigation-requests/generate").json()["draft"]
    assert draft["content"]["allergies_to_verify"], "the demo patient has a documented allergy"
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={}).status_code == 400
    substance = draft["content"]["allergies_to_verify"][0]["substance"]
    assert client.post(f"/api/drafts/{draft['id']}/verify-allergy", json={"substance": substance}).status_code == 200
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={}).status_code == 200


# ---------- Uploaded reports (F8) ----------

def test_uploaded_pdf_values_are_used(client):
    pdf = text_pdf([
        "CITY LAB REPORT",
        "Creatinine 1.0 mg/dL (0.7-1.3)",
        "eGFR 88 mL/min/1.73m2 (> 90)",
        "Potassium 4.1 mmol/L (3.5-5.1)",
    ])
    response = client.post("/api/documents/upload", files={"file": ("lab.pdf", pdf, "application/pdf")})
    assert response.status_code == 200, response.text
    fields = {f["name"].lower(): f["value"] for f in response.json()["extracted"]["fields"]}
    assert fields.get("creatinine") == "1.0"
    assert fields.get("egfr") == "88"


def test_upload_without_a_text_layer_returns_no_invented_values(client):
    response = client.post("/api/documents/upload", files={"file": ("scan.png", b"\x89PNG\r\n\x1a\n", "image/png")})
    assert response.status_code == 200
    body = response.json()
    assert body["extracted"]["fields"] == []
    assert body["ocr_status"] == "needs_manual_entry"


def test_low_confidence_field_blocks_commit(client):  # guard
    pdf = text_pdf(["Mystery 7"])
    doc = client.post("/api/documents/upload", files={"file": ("x.pdf", pdf, "application/pdf")}).json()
    fields = doc["extracted"]["fields"]
    if fields and any(f["confidence"] < 0.8 for f in fields):
        assert client.post(f"/api/documents/{doc['id']}/commit").status_code == 400


# ---------- Discharge lock and readiness (F9) ----------

def test_discharged_record_rejects_new_notes(client):
    assert discharge(client, override={"reason": "Test discharge with open alerts"}).status_code == 200
    response = client.post("/api/notes/generate", json={"feature": "F4", "transcript": SHORT_VISIT})
    assert response.status_code == 409


def test_discharged_record_rejects_new_tasks(client):
    assert discharge(client, override={"reason": "Test discharge with open alerts"}).status_code == 200
    assert client.post("/api/tasks", json={"title": "After discharge"}).status_code == 409


def test_empty_record_cannot_be_discharged(fresh):
    assert discharge(fresh).status_code == 409


def test_revenue_work_continues_after_discharge(client):
    assert discharge(client, override={"reason": "Test discharge with open alerts"}).status_code == 200
    assert client.post("/api/revenue/claim-prep/explain").status_code == 200


# ---------- Safety alerts (F5) ----------

def test_new_result_updates_the_existing_alert_instead_of_adding_one(client):
    inject_lab("eGFR", "18", "mL/min/1.73m²", "> 90", "low", datetime(2026, 10, 20, 10, 0))
    client.post("/api/alerts/evaluate")
    open_kidney = [a for a in client.get("/api/alerts").json()["alerts"] if a["rule_id"] == "R1" and a["status"] == "open"]
    assert len(open_kidney) == 1
    assert "18" in open_kidney[0]["explanation"]


def test_alert_closes_when_the_problem_is_gone(client):
    inject_event(
        type="med_order", title="Metformin stopped",
        payload={"drug": "Metformin", "kind": "inpatient", "status": "stopped"},
        source="test_feed", author_type="system", author_name="Test order feed",
        occurred_at=datetime(2026, 10, 20, 10, 5),
    )
    client.post("/api/alerts/evaluate")
    by_rule = {a["rule_id"]: a["status"] for a in client.get("/api/alerts").json()["alerts"]}
    assert by_rule["R1"] != "open"
    assert by_rule["R6"] != "open"


def test_dismissing_an_alert_needs_a_reason(client):  # guard
    alert = client.get("/api/alerts").json()["alerts"][0]
    assert client.post(f"/api/alerts/{alert['id']}/dismiss", json={"reason": "short"}).status_code == 422


def test_rules_are_not_decided_by_the_model(client):  # guard
    before = {a["id"] for a in client.get("/api/alerts").json()["alerts"]}
    generate_note(client, "F1", ASTHMA)
    assert {a["id"] for a in client.get("/api/alerts").json()["alerts"]} == before


# ---------- Tasks (F15) ----------

def _task(client, **body):
    payload = {"title": "Regression task", "owner": "Nurse Anita Rao", **body}
    response = client.post("/api/tasks", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_overdue_task_escalates_without_a_manual_sweep(client):
    task = _task(client, due_in_hours=-6)
    listed = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    assert listed[task["id"]]["escalation_level"] >= 1


def test_task_cannot_skip_acknowledgement(client):
    task = _task(client)
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"}).status_code in (400, 409)


def test_completed_task_cannot_be_reopened_without_a_reason(client):
    task = _task(client)
    client.post(f"/api/tasks/{task['id']}/acknowledge", json={"actor": "Nurse Anita Rao"})
    client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": "proposed"}).status_code in (400, 409)


def test_manual_escalation_needs_a_reason(client):
    task = _task(client)
    assert client.post(f"/api/tasks/{task['id']}/escalate", json={}).status_code in (400, 422)


def test_only_the_assignee_can_acknowledge(client):
    task = _task(client)
    response = client.post(f"/api/tasks/{task['id']}/acknowledge", json={"actor": "Someone Else"})
    assert response.status_code in (400, 403)


# ---------- Shared record (PRD page 3) and write path (rules 1 and 4) ----------

def test_new_result_reaches_every_consumer(client):  # guard
    inject_lab("eGFR", "18", "mL/min/1.73m²", "> 90", "low", datetime(2026, 10, 20, 10, 0))
    referral = client.post("/api/referrals/generate", json={}).json()["draft"]["content"]
    assert "18" in referral["question"]["text"]
    summary = client.post("/api/discharge/generate").json()["draft"]["content"]
    assert "egfr 18" in joined(summary)
    assert any(e["title"].startswith("eGFR — 18") for e in client.get("/api/patients/pat_ravi/timeline").json()["events"])


def test_drafts_write_nothing_to_the_timeline(client):  # guard
    before = client.get("/api/patients/pat_ravi/timeline").json()["count"]
    client.post("/api/referrals/generate", json={})
    client.post("/api/discharge/generate")
    client.post("/api/medications/reconciliation/generate")
    assert client.get("/api/patients/pat_ravi/timeline").json()["count"] == before


def test_round_proposes_tasks_without_creating_them(client):  # guard
    before = len(client.get("/api/tasks").json()["tasks"])
    draft = generate_note(client, "F3", "Doctor: Check potassium this morning.\nDoctor: Stop metformin until renal function improves.")
    assert draft["content"]["proposed_tasks"]
    assert len(client.get("/api/tasks").json()["tasks"]) == before


def test_consultation_needs_consent_to_sign(fresh):  # guard
    draft = generate_note(fresh, "F1", ASTHMA)
    assert fresh.post(f"/api/drafts/{draft['id']}/approve", json={}).status_code == 400


def test_progress_note_needs_clinician_exam_and_plan(client):  # guard
    draft = generate_note(client, "F4", SHORT_VISIT)
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={}).status_code == 400


def test_admission_note_needs_human_allergy_check(client):  # guard
    draft = generate_note(client, "F2", SHORT_VISIT)
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={}).status_code == 400


# ---------- helpers ----------

def _claims(value, out=None):
    out = [] if out is None else out
    if isinstance(value, dict):
        if isinstance(value.get("text"), str) and "source_segment_ids" in value:
            out.append(value)
        for item in value.values():
            _claims(item, out)
    elif isinstance(value, list):
        for item in value:
            _claims(item, out)
    return out
