"""F12 Insurance and TPA documentation: builds the claim pack, checks completeness, flags contradictions.

PRD line: "Builds the claim pack, checks completeness, flags contradictions before submission."
Seeded contradictions are set aside first so each test proves the check from events it injects itself.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.db import SessionLocal
from app.models import BillLineItem, Document, TimelineEvent

from .helpers import discharge, inject_event

NURSE = {"X-User-Id": "u_anita"}
MGMT = {"X-User-Id": "u_mgmt"}
BILLING = {"X-User-Id": "u_billing"}
DOCTOR = {"X-User-Id": "u_meera"}
OVERRIDE = {"reason": "Test discharge with open alerts"}
NOTE_TYPES = ["admission_note", "progress_note", "round_note", "consult_note", "nursing_note"]


def _set_status(event_id: str, status: str) -> None:
    db = SessionLocal()
    try:
        db.get(TimelineEvent, event_id).status = status
        db.commit()
    finally:
        db.close()


def _prep(client, headers=None) -> dict:
    response = client.get("/api/revenue/claim-prep", headers=headers or {})
    assert response.status_code == 200, response.text
    return response.json()


def _by_id(prep: dict, prefix: str) -> list[dict]:
    return [c for c in prep["contradictions"] if c["id"].startswith(prefix)]


def _quiet_allergy(client) -> None:
    """Set the seeded nursing allergy note aside so only injected notes can contradict."""
    assert len(_by_id(_prep(client), "contradiction_allergy")) == 1
    _set_status("evt_seed_nursing_contradiction", "superseded")
    assert _by_id(_prep(client), "contradiction_allergy") == []


def _quiet_hold(client) -> None:
    assert len(_by_id(_prep(client), "contradiction_plan_")) == 1
    _set_status("evt_seed_round", "superseded")
    assert _by_id(_prep(client), "contradiction_plan_") == []


def _note(note_type: str, body: str, payload: dict | None = None) -> str:
    return inject_event(
        type=note_type,
        title=f"Injected {note_type}",
        body_text=body,
        payload=payload or {},
        source="test_feed",
        author_type="human",
        author_name="Test author",
        occurred_at=datetime(2026, 10, 20, 9, 0),
    )


def _doc_present(prep: dict) -> dict[str, bool]:
    return {d["key"]: d["present"] for d in prep["required_documents"]}


# ---------- Allergy contradiction ----------

def test_seeded_allergy_contradiction_cites_the_allergy_record_and_the_note(client):
    found = _by_id(_prep(client), "contradiction_allergy")
    assert len(found) == 1
    assert found[0]["evidence_event_ids"] == ["evt_seed_allergy", "evt_seed_nursing_contradiction"]


@pytest.mark.parametrize("note_type", NOTE_TYPES)
def test_allergy_contradiction_fires_from_assertion_on_any_note_type(client, note_type):
    _quiet_allergy(client)
    note_id = _note(note_type, "Assessment done.", {"assertion": "no_known_allergies"})
    found = _by_id(_prep(client), "contradiction_allergy")
    assert len(found) == 1
    assert found[0]["evidence_event_ids"] == ["evt_seed_allergy", note_id]


@pytest.mark.parametrize("note_type", NOTE_TYPES)
@pytest.mark.parametrize("phrase", ["No known allergies.", "Patient has no known drug allergies."])
def test_allergy_contradiction_fires_from_note_text_on_any_note_type(client, note_type, phrase):
    _quiet_allergy(client)
    note_id = _note(note_type, f"Seen on the ward. {phrase} Plan unchanged.")
    found = _by_id(_prep(client), "contradiction_allergy")
    assert len(found) == 1
    assert found[0]["evidence_event_ids"] == ["evt_seed_allergy", note_id]
    assert phrase in [item["quote"] for item in found[0]["evidence"]]


def test_allergy_contradiction_ignores_notes_that_do_not_say_no_allergies(client):
    _quiet_allergy(client)
    _note("admission_note", "Patient reports a penicillin allergy with rash.")
    assert _by_id(_prep(client), "contradiction_allergy") == []


def test_allergy_contradiction_clears_when_the_note_is_superseded(client):
    _quiet_allergy(client)
    note_id = _note("consult_note", "No known drug allergies.")
    assert len(_by_id(_prep(client), "contradiction_allergy")) == 1
    _set_status(note_id, "superseded")
    assert _by_id(_prep(client), "contradiction_allergy") == []


def test_allergy_contradiction_needs_a_documented_allergy(client):
    _quiet_allergy(client)
    _note("nursing_note", "No known drug allergies.")
    assert len(_by_id(_prep(client), "contradiction_allergy")) == 1
    _set_status("evt_seed_allergy", "superseded")
    assert _by_id(_prep(client), "contradiction_allergy") == []


# ---------- Medicine-hold contradiction ----------

def test_hold_contradiction_from_open_plan_action_cites_both_events(client):
    found = _by_id(_prep(client), "contradiction_plan_metformin")
    assert len(found) == 1
    assert found[0]["evidence_event_ids"] == ["evt_seed_round", "evt_seed_med_metformin"]


@pytest.mark.parametrize("phrase", ["Stop metformin until renal function improves.", "Hold metformin today."])
def test_hold_contradiction_fires_from_round_note_text_alone(client, phrase):
    _quiet_hold(client)
    note_id = _note("round_note", f"Ward round. {phrase}")
    found = _by_id(_prep(client), "contradiction_plan_metformin")
    assert len(found) == 1
    assert found[0]["evidence_event_ids"] == [note_id, "evt_seed_med_metformin"]
    assert phrase in [item["quote"] for item in found[0]["evidence"]]


def test_hold_contradiction_fires_from_note_claims_text(client):
    _quiet_hold(client)
    note_id = _note("round_note", "Ward round.", {"note_claims": [{"text": "Hold metformin until review."}]})
    found = _by_id(_prep(client), "contradiction_plan_metformin")
    assert [c["evidence_event_ids"] for c in found] == [[note_id, "evt_seed_med_metformin"]]


def test_hold_contradiction_clears_when_the_plan_action_is_resolved(client):
    _quiet_hold(client)
    open_note = _note(
        "round_note",
        "Stop metformin until renal function improves.",
        {"plan_actions": [{"action": "hold", "drug": "Metformin", "status": "open"}]},
    )
    assert len(_by_id(_prep(client), "contradiction_plan_metformin")) == 1
    _set_status(open_note, "superseded")
    _note(
        "round_note",
        "Stop metformin until renal function improves.",
        {"plan_actions": [{"action": "hold", "drug": "Metformin", "status": "resolved"}]},
    )
    assert _by_id(_prep(client), "contradiction_plan_metformin") == []


def test_hold_contradiction_clears_when_the_drug_is_stopped(client):
    assert len(_by_id(_prep(client), "contradiction_plan_metformin")) == 1
    inject_event(
        type="med_order", title="Metformin stopped",
        payload={"drug": "Metformin", "kind": "inpatient", "status": "stopped"},
        source="test_feed", author_type="system", author_name="Test order feed",
        occurred_at=datetime(2026, 10, 20, 10, 5),
    )
    assert _by_id(_prep(client), "contradiction_plan_metformin") == []


def test_hold_contradiction_clears_when_the_note_is_superseded(client):
    _quiet_hold(client)
    note_id = _note("round_note", "Hold metformin.")
    assert len(_by_id(_prep(client), "contradiction_plan_metformin")) == 1
    _set_status(note_id, "superseded")
    assert _by_id(_prep(client), "contradiction_plan_metformin") == []


@pytest.mark.parametrize("phrase", ["Do not stop metformin.", "We will not hold metformin."])
def test_negated_hold_text_is_not_a_contradiction(client, phrase):
    _quiet_hold(client)
    _note("round_note", phrase)
    assert _by_id(_prep(client), "contradiction_plan_metformin") == []


def test_hold_text_for_a_drug_that_is_not_active_is_not_a_contradiction(client):
    _quiet_hold(client)
    _note("round_note", "Stop digoxin.")
    assert _by_id(_prep(client), "contradiction_plan_") == []


def test_every_clinical_contradiction_cites_two_distinct_events_with_quotes(client):
    _note("nursing_note", "No known allergies.")
    clinical = [c for c in _prep(client)["contradictions"] if c["kind"] in {"clinical_record", "medication"}]
    assert {c["kind"] for c in clinical} == {"clinical_record", "medication"}
    for item in clinical:
        assert len(set(item["evidence_event_ids"])) == 2
        assert [e["event_id"] for e in item["evidence"]] == item["evidence_event_ids"]
        assert all(e["quote"] for e in item["evidence"])


# ---------- Completeness ----------

def test_completeness_flips_when_the_discharge_is_signed(client):
    before = _prep(client)
    assert before["discharge_signed"] is False
    assert _doc_present(before)["signed_discharge"] is False
    assert "Signed discharge summary" in [d["label"] for d in before["missing_documents"]]
    assert discharge(client, override=OVERRIDE).status_code == 200
    after = _prep(client)
    assert after["discharge_signed"] is True
    assert _doc_present(after)["signed_discharge"] is True
    assert "Signed discharge summary" not in [d["label"] for d in after["missing_documents"]]
    assert len(after["missing_documents"]) == len(before["missing_documents"]) - 1


def test_completeness_flips_when_a_pre_authorisation_document_is_matched(client):
    before = _prep(client)
    assert _doc_present(before)["pre_auth"] is False
    # A lab report cannot answer a pre-authorisation request (the earlier version of this test
    # matched doc_seed_outside, a lab report, and treated the flip as success).
    refused = client.post("/api/document-requests/req_seed_preauth/match", json={"document_id": "doc_seed_outside"})
    assert refused.status_code == 400, refused.text
    assert _doc_present(_prep(client))["pre_auth"] is False
    db = SessionLocal()
    try:
        db.add(
            Document(
                id="doc_test_preauth",
                patient_id="pat_ravi",
                encounter_id=db.get(Document, "doc_seed_outside").encounter_id,
                filename="star_health_preauth.pdf",
                mime="application/pdf",
                path="",
                image_kind="file",
                doc_type="pre_auth",
                ocr_status="reviewed",
                extracted={"fields": []},
            )
        )
        db.commit()
    finally:
        db.close()
    matched = client.post("/api/document-requests/req_seed_preauth/match", json={"document_id": "doc_test_preauth"})
    assert matched.status_code == 200, matched.text
    after = _prep(client)
    assert _doc_present(after)["pre_auth"] is True
    assert "Pre-authorization approval" not in [d["label"] for d in after["missing_documents"]]
    assert len(after["missing_documents"]) == len(before["missing_documents"]) - 1


# ---------- Claim pack HTML ----------

def test_claim_pack_escapes_note_text(client):
    _quiet_allergy(client)
    _note("nursing_note", "Patient has no known drug allergies <script>alert(1)</script> today.")
    html = client.get("/api/revenue/claim-prep/pack.html").text
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_claim_pack_escapes_a_script_in_a_billed_description(client):
    db = SessionLocal()
    try:
        item = db.query(BillLineItem).first()
        item.description = "<script>steal()</script>"
        db.commit()
    finally:
        db.close()
    html = client.get("/api/revenue/claim-prep/pack.html").text
    assert "<script>" not in html
    assert "&lt;script&gt;steal()&lt;/script&gt;" in html


def test_claim_pack_shows_status_review_only_line_and_every_gap_with_evidence(client):
    prep = _prep(client)
    assert prep["missing_documents"] and prep["contradictions"]
    html = client.get("/api/revenue/claim-prep/pack.html").text
    assert "Review only: nothing is submitted." in html
    assert f"Status: {prep['status'].replace('_', ' ')}" in html
    gap_table = html.split("<h2>Documentation gaps</h2>")[1].split("</table>")[0]
    for item in prep["missing_documents"]:
        assert item["label"] in gap_table
    for item in prep["contradictions"]:
        assert item["title"] in gap_table
        for event_id in item["evidence_event_ids"]:
            assert event_id in gap_table
    for item in prep["unbilled_procedures"]:
        assert item["procedure"] in gap_table
        assert item["event_id"] in gap_table
    for item in prep["unsupported_items"]:
        assert item["description"] in gap_table
    for item in prep["underbilled_items"]:
        assert item["description"] in gap_table
        assert item["evidence_event_ids"][0] in gap_table


# ---------- Who may do claim work ----------

def test_claim_work_is_allowed_after_discharge(client):
    assert discharge(client, override=OVERRIDE).status_code == 200
    assert client.post("/api/revenue/claim-prep/prepare").status_code == 200
    assert client.post("/api/revenue/claim-prep/explain").status_code == 200


@pytest.mark.parametrize("headers", [NURSE, MGMT])
def test_nurse_and_management_cannot_prepare_or_explain_but_can_read(client, headers):
    assert client.post("/api/revenue/claim-prep/prepare", headers=headers).status_code == 403
    assert client.post("/api/revenue/claim-prep/explain", headers=headers).status_code == 403
    assert client.get("/api/revenue/claim-prep", headers=headers).status_code == 200


@pytest.mark.parametrize("headers", [BILLING, DOCTOR])
def test_billing_and_doctor_can_prepare_and_explain(client, headers):
    prepared = client.post("/api/revenue/claim-prep/prepare", headers=headers)
    assert prepared.status_code == 200
    assert prepared.json()["review"]["status"] == "needs_clarification"
    assert client.post("/api/revenue/claim-prep/explain", headers=headers).status_code == 200


def test_tpa_state_follows_the_contradictions(client):
    before = _prep(client)
    assert before["status"] == "needs_clarification"
    assert before["tpa_review"]["status"] == "needs_clarification"
    assert before["tpa_review"]["contradiction_count"] == len(before["contradictions"])
    _set_status("evt_seed_nursing_contradiction", "superseded")
    _set_status("evt_seed_round", "superseded")
    after = _prep(client)
    assert {c["kind"] for c in after["contradictions"]} <= {"billing_documentation"}
    assert after["tpa_review"]["contradiction_count"] == len(after["contradictions"])
    assert len(after["contradictions"]) < len(before["contradictions"])
