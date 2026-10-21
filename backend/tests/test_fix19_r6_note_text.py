"""F5 (scan F05-3): a plan to stop or hold a medicine, written in the app, is an unresolved action (R6).

PRD: "Checks drugs, labs, contradicting notes and unresolved actions, with evidence attached."
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.models import Alert, AuditEntry, TimelineEvent

from .helpers import generate_note, inject_event

METFORMIN_ORDER = "evt_seed_med_metformin"
STOP = "Doctor: Stop metformin until renal function improves."
BENIGN = "Doctor: The leg is less red today.\nDoctor: Continue IV flucloxacillin and review tomorrow."


def _approve(client, transcript: str) -> str:
    draft = generate_note(client, "F3", transcript)
    response = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert response.status_code == 200, response.text
    return response.json()["event"]["id"]


def _r6(drug: str = "metformin") -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(Alert).filter(Alert.patient_id == "pat_ravi", Alert.dedupe_key == f"rule:R6:{drug}").all()
        return [
            {"id": r.id, "status": r.status, "evidence": list(r.evidence_event_ids or []),
             "resolution": r.resolution, "resolved_at": r.resolved_at}
            for r in rows
        ]
    finally:
        db.close()


def _open_r6(drug: str = "metformin") -> list[dict]:
    return [row for row in _r6(drug) if row["status"] == "open"]


def _audits(action: str, entity_id: str | None = None) -> int:
    db = SessionLocal()
    try:
        query = db.query(AuditEntry).filter(AuditEntry.action == action)
        if entity_id:
            query = query.filter(AuditEntry.entity_id == entity_id)
        return query.count()
    finally:
        db.close()


def test_a_stop_plan_written_in_the_app_raises_an_unresolved_action_alert_with_both_sources(client):
    note_id = _approve(client, STOP)
    rows = _r6()
    assert len(rows) == 1
    assert rows[0]["status"] == "open"
    assert set(rows[0]["evidence"]) == {note_id, METFORMIN_ORDER}
    alert = next(a for a in client.get("/api/alerts").json()["alerts"] if a["id"] == rows[0]["id"])
    assert alert["rule_id"] == "R6"
    assert "Stop metformin until renal function improves." in alert["explanation"]


@pytest.mark.parametrize(
    "sentence",
    ["Hold metformin until renal function improves.", "Withhold the metformin today."],
)
def test_every_stop_verb_the_claim_check_knows_raises_the_alert(client, sentence):
    note_id = _approve(client, f"Doctor: {sentence}")
    (row,) = _open_r6()
    assert note_id in row["evidence"] and METFORMIN_ORDER in row["evidence"]


def test_a_negated_plan_raises_no_unresolved_action_alert(client):
    _approve(client, "Doctor: Do not stop metformin, renal function is stable.")
    assert _open_r6() == []


def test_a_note_about_a_drug_that_is_not_ordered_raises_nothing_for_it(client):
    _approve(client, "Doctor: Stop aspirin if the pain settles.")
    assert _r6("aspirin") == []


def test_stopping_the_drug_resolves_the_alert_with_no_longer_true(client):
    _approve(client, STOP)
    (row,) = _open_r6()
    response = client.post(
        "/api/medications/orders",
        json={"action": "stop", "drug": "Metformin", "reason": "Renal function is poor, stopping as planned"},
    )
    assert response.status_code == 200, response.text
    (after,) = _r6()
    assert after["id"] == row["id"]
    assert after["status"] == "resolved"
    assert after["resolution"].startswith("No longer true")
    assert after["resolved_at"] is not None
    assert _audits("alert_auto_resolved", row["id"]) == 1


def test_a_superseded_note_raises_no_alert(client):
    first = _approve(client, STOP)
    assert len(_open_r6()) == 1
    _approve(client, BENIGN)
    db = SessionLocal()
    try:
        assert db.get(TimelineEvent, first).status == "superseded"
    finally:
        db.close()
    assert _open_r6() == []
    (row,) = _r6()
    assert row["status"] == "resolved" and row["resolution"].startswith("No longer true")


def test_evaluating_twice_leaves_exactly_one_open_alert(client):
    _approve(client, STOP)
    (first,) = _open_r6()
    created, updated = _audits("alert_created"), _audits("alert_updated")
    for _ in range(2):
        assert client.post("/api/alerts/evaluate").json()["created"] == []
    rows = _r6()
    assert len(rows) == 1 and rows[0] == first
    assert _audits("alert_created") == created
    assert _audits("alert_updated") == updated


def test_a_plan_action_on_the_same_note_decides_over_the_note_text(client):
    # Approving a note supersedes the seeded one; then add a note that carries text and a closed plan action.
    _approve(client, BENIGN)
    assert _open_r6() == []
    inject_event(
        type="round_note", title="Ward round with a closed plan action",
        body_text="Stop metformin until renal function improves.",
        payload={"note_claims": ["Stop metformin until renal function improves."],
                 "plan_actions": [{"action": "hold", "drug": "Metformin", "status": "resolved"}]},
        source="test_feed", author_type="system", author_name="Test feed", status="approved",
    )
    client.post("/api/alerts/evaluate")
    assert _open_r6() == []


def test_discontinue_in_an_approved_round_note_raises_the_alert(client):
    # The draft extractor does not treat "discontinue" as a plan verb, so the approved note is written directly.
    _approve(client, BENIGN)
    note_id = inject_event(
        type="round_note", title="Ward round", body_text="Discontinue metformin now.",
        payload={"note_claims": [{"text": "Discontinue metformin now."}]},
        source="test_feed", author_type="system", author_name="Test feed", status="approved",
    )
    client.post("/api/alerts/evaluate")
    (row,) = _open_r6()
    assert set(row["evidence"]) == {note_id, METFORMIN_ORDER}
