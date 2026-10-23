"""F5 clinical guardrail: one alert per problem, closes when the problem is gone, measured precision."""

from __future__ import annotations

import ast
import inspect
from datetime import datetime

import pytest

from app.db import SessionLocal
from app.models import Alert, AuditEntry

from .helpers import generate_note, inject_event, inject_lab

DOCTOR = {"X-User-Id": "u_meera"}
DISMISS = {"category": "known_and_accepted", "reason": "Reviewed and accepted by the team"}


def _rows(patient_id="pat_ravi"):
    db = SessionLocal()
    try:
        rows = db.query(Alert).filter(Alert.patient_id == patient_id).all()
        return {
            row.dedupe_key: {
                "id": row.id, "rule_id": row.rule_id, "status": row.status, "evidence": list(row.evidence_event_ids or []),
                "category": row.dismissal_category, "resolution": row.resolution, "resolved_at": row.resolved_at,
            }
            for row in rows
        }
    finally:
        db.close()


def _audits(action, entity_id=None):
    db = SessionLocal()
    try:
        query = db.query(AuditEntry).filter(AuditEntry.action == action)
        if entity_id:
            query = query.filter(AuditEntry.entity_id == entity_id)
        return query.count()
    finally:
        db.close()


def _api_alerts(client):
    return {a["id"]: a for a in client.get("/api/alerts").json()["alerts"]}


def _by_rule(client, rule_id, status=None):
    return [a for a in _api_alerts(client).values() if a["rule_id"] == rule_id and (status is None or a["status"] == status)]


def _stop_metformin():
    inject_event(
        type="med_order", title="Metformin stopped",
        payload={"drug": "Metformin", "kind": "inpatient", "status": "stopped"},
        source="test_feed", author_type="system", author_name="Test order feed",
        occurred_at=datetime(2026, 10, 20, 10, 5),
    )


# ---------- one alert per problem ----------

def test_alert_keys_are_stable_and_name_the_problem(client):
    keys = set(_rows())
    expected = {
        "rule:R1:metformin",
        "rule:R2:flucloxacillin",
        "rule:R3:creatinine",
        "rule:R4:warfarin+ibuprofen",
        "rule:R5:evt_seed_nursing_contradiction",
        "rule:R6:metformin",
    }
    assert expected <= keys
    assert all(key.startswith("rule:") for key in keys)


def test_one_open_alert_per_problem_after_two_evaluations(client):
    client.post("/api/alerts/evaluate")
    first = _rows()
    created_before = _audits("alert_created")
    updated_before = _audits("alert_updated")
    assert client.post("/api/alerts/evaluate").json()["created"] == []
    second = _rows()
    assert second == first
    assert _audits("alert_created") == created_before
    assert _audits("alert_updated") == updated_before
    assert len([a for a in _by_rule(client, "R1")]) == 1


def test_new_result_updates_the_open_alert_in_place_and_audits_the_change(client):
    before = _rows()["rule:R1:metformin"]
    lab_id = inject_lab("eGFR", "15", "mL/min/1.73m²", "> 90", "low", datetime(2026, 10, 20, 11, 0))
    created = client.post("/api/alerts/evaluate").json()["created"]
    assert [a for a in created if a["rule_id"] == "R1"] == []  # updated in place, not created or reopened
    after = _rows()["rule:R1:metformin"]
    assert after["id"] == before["id"] and after["status"] == "open"
    assert lab_id in after["evidence"] and "evt_seed_lab_egfr" not in after["evidence"]
    assert "15" in _api_alerts(client)[before["id"]]["explanation"]
    assert _audits("alert_updated", before["id"]) == 1


def test_dismissed_alert_stays_dismissed_until_a_newer_result_arrives(client):
    alert_id = _rows()["rule:R1:metformin"]["id"]
    assert client.post(f"/api/alerts/{alert_id}/dismiss", json=DISMISS).status_code == 200
    client.post("/api/alerts/evaluate")
    assert _api_alerts(client)[alert_id]["status"] == "dismissed"
    assert _audits("alert_reopened", alert_id) == 0

    inject_lab("eGFR", "15", "mL/min/1.73m²", "> 90", "low", datetime(2026, 10, 20, 11, 0))
    reopened = client.post("/api/alerts/evaluate").json()["created"]
    assert [a["id"] for a in reopened if a["rule_id"] == "R1"] == [alert_id]
    row = _api_alerts(client)[alert_id]
    assert row["status"] == "open"
    assert _audits("alert_reopened", alert_id) == 1
    assert len(_by_rule(client, "R1")) == 1


def test_two_different_labs_make_two_result_alerts(client):
    inject_lab("Sodium", "126", "mmol/L", "135-145", "low", datetime(2026, 10, 20, 9, 0))
    client.post("/api/alerts/evaluate")
    keys = [key for key in _rows() if key.startswith("rule:R3:")]
    assert "rule:R3:creatinine" in keys and "rule:R3:sodium" in keys
    open_r3 = [a for a in _by_rule(client, "R3", "open")]
    assert len(open_r3) == len(keys)
    assert len({a["id"] for a in open_r3}) == len(open_r3)


def test_second_result_for_the_same_lab_does_not_add_a_result_alert(client):
    count = len(_by_rule(client, "R3"))
    inject_lab("Creatinine", "3.4", "mg/dL", "0.7-1.3", "high", datetime(2026, 10, 20, 12, 0))
    client.post("/api/alerts/evaluate")
    assert len(_by_rule(client, "R3")) == count


# ---------- closing alerts ----------

def test_alert_closes_with_a_reason_when_the_drug_is_stopped(client):
    ids = {key: _rows()[key]["id"] for key in ("rule:R1:metformin", "rule:R6:metformin")}
    _stop_metformin()
    client.post("/api/alerts/evaluate")
    shown = _api_alerts(client)
    for key, alert_id in ids.items():
        assert shown[alert_id]["status"] == "resolved", key
        assert shown[alert_id]["resolution"].startswith("No longer true: ")
        assert shown[alert_id]["resolved_at"]
        assert _audits("alert_auto_resolved", alert_id) == 1
    # Unrelated alerts stay open.
    assert shown[_rows()["rule:R4:warfarin+ibuprofen"]["id"]]["status"] == "open"


def test_a_closed_alert_is_left_alone_when_nothing_changed(client):
    _stop_metformin()
    client.post("/api/alerts/evaluate")
    snapshot = _rows()
    resolved_audits = _audits("alert_auto_resolved")
    client.post("/api/alerts/evaluate")
    assert _rows() == snapshot
    assert _audits("alert_auto_resolved") == resolved_audits


def test_alert_without_the_rule_prefix_is_never_auto_resolved(client):
    db = SessionLocal()
    db.add(Alert(
        id="alr_legacy", patient_id="pat_ravi", encounter_id="enc_ipd_1", rule_id="R1",
        dedupe_key="R1:metformin:evt_old", severity="critical", status="open", title="Old style alert",
        evidence_event_ids=[],
    ))
    db.commit()
    db.close()
    client.post("/api/alerts/evaluate")
    assert _rows()["R1:metformin:evt_old"]["status"] == "open"


def test_reviewing_a_result_acknowledges_only_that_labs_alert(client):
    inject_lab("Sodium", "126", "mmol/L", "135-145", "low", datetime(2026, 10, 20, 9, 0))
    client.post("/api/alerts/evaluate")
    rows = _rows()
    assert rows["rule:R3:creatinine"]["status"] == "open" and rows["rule:R3:sodium"]["status"] == "open"
    assert client.post("/api/labs/evt_seed_lab_creatinine/review").status_code == 200
    rows = _rows()
    assert rows["rule:R3:creatinine"]["status"] == "acknowledged"
    assert rows["rule:R3:sodium"]["status"] == "open"
    # The reviewed alert is not recreated by the next run.
    client.post("/api/alerts/evaluate")
    assert _rows()["rule:R3:creatinine"]["status"] == "acknowledged"


# ---------- R5: a note written in the app ----------

NKDA_VISIT = (
    "Doctor: Good morning.\nPatient: I have a cough.\nPatient: No known drug allergies.\n"
    "Doctor: Review in four weeks."
)


def _consent(client):
    response = client.post(
        "/api/patients/pat_ravi/consents", json={"consent_type": "consultation_capture", "granted": True}
    )
    assert response.status_code == 200, response.text


def test_contradicting_allergy_rule_fires_after_an_approved_note_says_no_known_allergies(client):
    _consent(client)
    before = {key for key in _rows() if key.startswith("rule:R5:")}
    draft = generate_note(client, "F1", NKDA_VISIT)
    response = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert response.status_code == 200, response.text
    event_id = response.json()["draft"]["committed_event_id"]
    fired = [a for a in response.json()["new_alerts"] if a["rule_id"] == "R5"]
    assert len(fired) == 1
    assert f"rule:R5:{event_id}" in set(_rows()) - before
    alert = _api_alerts(client)[fired[0]["id"]]
    assert event_id in alert["evidence_event_ids"]  # evidence points at the note


def test_note_that_does_not_deny_allergies_raises_no_contradiction(client):
    _consent(client)
    before = {key for key in _rows() if key.startswith("rule:R5:")}
    draft = generate_note(client, "F1", "Doctor: Hello.\nPatient: I have a cough.\nDoctor: Review in four weeks.")
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={}).status_code == 200
    assert {key for key in _rows() if key.startswith("rule:R5:")} == before


def test_no_known_allergies_wording_is_matched_and_nothing_else():
    from app.services.approval.f05_assertion import says_no_known_allergies

    def claim(text):
        return {"plan": [{"text": text, "source_segment_ids": ["seg_1"]}]}

    for text in ("No known drug allergies.", "no known allergies", "NKDA", "Pt NKA today"):
        assert says_no_known_allergies(claim(text)), text
    for text in ("Penicillin allergy, rash.", "Allergies were not discussed.", "Known allergy to penicillin"):
        assert not says_no_known_allergies(claim(text)), text


def test_assertion_builder_is_registered_for_every_note_feature():
    from app.services.approval import PAYLOAD_BUILDERS
    from app.services.approval.f05_assertion import mark_no_known_allergies

    for feature in ("F1", "F2", "F3", "F4"):
        assert mark_no_known_allergies in PAYLOAD_BUILDERS[feature]


# ---------- dismissal ----------

def _first_open(client):
    return next(a for a in client.get("/api/alerts").json()["alerts"] if a["status"] == "open")


def test_dismissal_needs_a_category_and_a_reason(client):
    alert = _first_open(client)
    url = f"/api/alerts/{alert['id']}/dismiss"
    assert client.post(url, json={"reason": "Reviewed and accepted by the team"}).status_code == 422
    assert client.post(url, json={"category": "whatever", "reason": "Reviewed and accepted by the team"}).status_code == 422
    assert client.post(url, json={"category": "acted_on", "reason": "short"}).status_code == 422
    assert _api_alerts(client)[alert["id"]]["status"] == "open"


def test_dismissal_stores_the_category_and_reason(client):
    alert = _first_open(client)
    body = {"category": "false_positive", "reason": "The result was a transcription error"}
    assert client.post(f"/api/alerts/{alert['id']}/dismiss", json=body).status_code == 200
    saved = _api_alerts(client)[alert["id"]]
    assert saved["status"] == "dismissed"
    assert saved["dismissal_category"] == "false_positive"
    assert saved["dismissal_reason"] == "The result was a transcription error"
    assert _audits("alert_dismissed", alert["id"]) == 1


# ---------- measuring usefulness ----------

def _quality(client, **kwargs):
    body = client.get("/api/alerts/quality", **kwargs).json()
    return body, {rule["rule_id"]: rule for rule in body["rules"]}


def _add_alerts(rule_id, statuses_and_categories):
    db = SessionLocal()
    for number, (status, category) in enumerate(statuses_and_categories):
        db.add(Alert(
            id=f"alr_q_{rule_id}_{number}", patient_id="pat_ravi", encounter_id="enc_ipd_1", rule_id=rule_id,
            dedupe_key=f"hand:{rule_id}:{number}", severity="warning", status=status, title="Hand-built",
            dismissal_category=category, evidence_event_ids=[],
        ))
    db.commit()
    db.close()


def test_quality_precision_is_useful_dismissals_over_categorised_dismissals(client):
    base_body, base = _quality(client)
    assert [rule["rule_id"] for rule in base_body["rules"]] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    assert base_body["note"] == "Small sample: based on clinician dismissals."
    assert all(rule["precision"] is None for rule in base.values())  # nothing categorised yet
    assert base_body["sample_size"] == 0

    _add_alerts("R2", [
        ("dismissed", "false_positive"),
        ("dismissed", "known_and_accepted"),
        ("dismissed", "known_and_accepted"),
        ("dismissed", "acted_on"),
        ("open", None),
        ("resolved", None),
    ])
    _add_alerts("R1", [("dismissed", "false_positive")])
    body, rules = _quality(client)
    r2 = rules["R2"]
    assert r2["opened"] == base["R2"]["opened"] + 6
    assert r2["open"] == base["R2"]["open"] + 1
    assert r2["auto_resolved"] == base["R2"]["auto_resolved"] + 1
    assert (r2["false_positive"], r2["known_and_accepted"], r2["acted_on"]) == (1, 2, 1)
    assert r2["precision"] == 0.75
    assert rules["R1"]["precision"] == 0.0
    assert rules["R6"]["precision"] is None
    assert body["sample_size"] == 5


def test_quality_counts_every_patient(client):
    db = SessionLocal()
    db.add(Alert(
        id="alr_q_other", patient_id="pat_joseph", encounter_id=None, rule_id="R3", dedupe_key="hand:other",
        status="dismissed", title="Other patient", dismissal_category="acted_on", evidence_event_ids=[],
    ))
    db.commit()
    db.close()
    _, rules = _quality(client)
    assert rules["R3"]["acted_on"] == 1
    assert rules["R3"]["precision"] == 1.0


# ---------- the model never decides ----------

def test_rules_never_call_a_model(client, monkeypatch):  # guard
    import app.services.llm as llm
    import app.services.rules as rules

    tree = ast.parse(inspect.getsource(rules))
    imported = " ".join(
        (getattr(node, "module", None) or "") + " " + " ".join(alias.name for alias in node.names)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ).lower()
    assert "llm" not in imported and "openai" not in imported

    def refuse(*args, **kwargs):
        raise AssertionError("the rules called a model")

    for name, value in vars(llm).items():
        if inspect.isfunction(value) and value.__module__ == llm.__name__:
            monkeypatch.setattr(llm, name, refuse)
    assert client.post("/api/alerts/evaluate").status_code == 200
    _stop_metformin()
    assert client.post("/api/alerts/evaluate").status_code == 200


def test_every_alert_names_its_evidence(client):  # guard (PRD rule 3)
    for alert in client.get("/api/alerts").json()["alerts"]:
        if alert["rule_id"] in {"R1", "R2", "R3", "R4", "R5", "R6"}:
            assert alert["evidence_event_ids"], alert["title"]
