"""F11 Smart referrals: history from the record, the specific question, and tracking of the consult.

PRD: "Sends the specialist the history and the specific question; tracks the consult."
Rules 1 (a clinician decides), 2 (never invent), 3 (show the evidence).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Referral

from .helpers import inject_lab, joined

PATIENT = "pat_ravi"
PLACEHOLDER = "Question to be written by the referring clinician"
NURSE = {"X-User-Id": "u_anita"}
PHARMACIST = {"X-User-Id": "u_dev"}
BILLING = {"X-User-Id": "u_billing"}
MGMT = {"X-User-Id": "u_mgmt"}
QUESTION = "Please advise on whether the falling kidney function needs a change of the current medicines."


def _state(client) -> dict:
    return client.get(f"/api/patients/{PATIENT}/state").json()


def _generate(client, **body) -> dict:
    response = client.post("/api/referrals/generate", json=body)
    assert response.status_code == 200, response.text
    return response.json()["draft"]


def _approve(client, draft) -> dict:
    response = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert response.status_code == 200, response.text
    return response.json()


def _referrals(client) -> list[dict]:
    return client.get("/api/referrals").json()["referrals"]


def _sent_referral(client) -> dict:
    """Approve a new referral and return it (the rehearsal record may already hold others)."""
    known = {r["id"] for r in _referrals(client)}
    draft = _generate(client, specialty="Cardiology", question=QUESTION)
    _approve(client, draft)
    new = [r for r in _referrals(client) if r["id"] not in known]
    assert len(new) == 1
    assert new[0]["draft_id"] == draft["id"]
    return new[0]


def _timeline(client) -> list[dict]:
    return client.get(f"/api/patients/{PATIENT}/timeline").json()["events"]


def test_renal_referral_cites_the_new_egfr_when_one_arrives(client):
    before = _generate(client)["content"]
    assert before["specialty"] == "Nephrology"
    event_id = inject_lab("eGFR", "31", "mL/min/1.73m²", "> 90", "low", datetime(2026, 10, 20, 9, 0))
    content = _generate(client)["content"]
    assert content["specialty"] == "Nephrology"
    egfr = [claim for claim in content["relevant_results"] if claim["text"].startswith("eGFR")]
    assert [claim["source_event_ids"] for claim in egfr] == [[event_id]]
    assert "31" in egfr[0]["text"]
    assert event_id in content["history"]["source_event_ids"]
    assert "egfr 22" not in joined(content)


def test_cardiology_request_carries_no_nephrology_wording(client):
    draft = _generate(client, specialty="Cardiology")
    content = draft["content"]
    text = joined(content)
    assert content["specialty"] == "Cardiology"
    for word in ("nephrolog", "dialysis", "co-management", "dose adjustment"):
        assert word not in text
    assert content["specialist"] == "Cardiology service"


def test_history_age_sex_and_problems_equal_the_patient_record(client):
    patient = _state(client)["patient"]
    history = _generate(client, specialty="Cardiology")["content"]["history"]["text"]
    assert f"{patient['age']}-year-old" in history
    assert patient["sex"].lower() in history
    for problem in patient["problems"]:
        assert problem in history


def test_history_quotes_approved_assessment_lines_and_cites_their_events(client):
    events = [e for e in _timeline(client) if e["type"] in {"consult_note", "admission_note"} and e["status"] == "approved"]
    admission = next(e for e in events if e["type"] == "admission_note")
    lines = admission["payload"]["assessment"]
    assert lines, "the rehearsal admission note documents an assessment"
    history = _generate(client, specialty="Cardiology")["content"]["history"]
    for line in lines:
        assert f'"{line}"' in history["text"]
    assert admission["id"] in history["source_event_ids"]


def test_history_lists_abnormal_results_with_their_event_ids(client):
    abnormal = [lab for lab in _state(client)["latest_labs"] if lab["flag"] in {"high", "low"}]
    assert abnormal
    content = _generate(client, specialty="Cardiology")["content"]
    cited = {claim["source_event_ids"][0]: claim["text"] for claim in content["relevant_results"]}
    assert set(cited) == {lab["event_id"] for lab in abnormal}
    for lab in abnormal:
        assert str(lab["value"]) in cited[lab["event_id"]]
        assert lab["event_id"] in content["history"]["source_event_ids"]


def test_referral_without_specialty_on_an_empty_record_is_422_choose_a_specialty(fresh):
    response = fresh.post("/api/referrals/generate", json={})
    assert response.status_code == 422
    assert response.json()["detail"] == "Choose a specialty"
    assert fresh.get("/api/drafts?feature=F11").json()["drafts"] == []


def test_empty_record_referral_with_a_specialty_holds_only_the_patient_record(fresh):
    patient = _state(fresh)["patient"]
    content = _generate(fresh, specialty="Cardiology")["content"]
    assert content["relevant_results"] == []
    assert content["history"]["source_event_ids"] == []
    assert f"{patient['age']}-year-old" in content["history"]["text"]
    assert "Abnormal results" not in content["history"]["text"]
    assert "Assessment in approved notes" not in content["history"]["text"]


def test_unrequested_question_is_the_marked_placeholder_with_zero_confidence(client):
    question = _generate(client, specialty="Cardiology")["content"]["question"]
    assert question["text"] == PLACEHOLDER
    assert question["confidence"] == 0


def test_supplied_question_is_used_verbatim(client):
    question = _generate(client, specialty="Cardiology", question=f"  {QUESTION} ")["content"]["question"]
    assert question["text"] == QUESTION
    assert question["confidence"] == 1.0


def test_urgency_defaults_to_routine_and_the_supplied_one_is_kept(client):
    assert _generate(client)["content"]["urgency"] == "routine"
    assert _generate(client, urgency="emergency")["content"]["urgency"] == "emergency"
    assert client.post("/api/referrals/generate", json={"urgency": "whenever"}).status_code == 422


def test_placeholder_question_blocks_approval_and_an_edited_question_passes(client):
    known = {r["id"] for r in _referrals(client)}
    draft = _generate(client, specialty="Cardiology")
    refused = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert refused.status_code == 400
    assert "question" in refused.json()["detail"].lower()
    assert {r["id"] for r in _referrals(client)} == known
    # an override reason does not get past it: the clinician must write the question
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={"override": {"reason": "in a hurry"}}).status_code == 400
    content = dict(draft["content"])
    content["question"] = {**content["question"], "text": QUESTION, "confidence": 1.0}
    assert client.patch(f"/api/drafts/{draft['id']}", json={"content": content}).status_code == 200
    _approve(client, draft)
    created = [r for r in _referrals(client) if r["id"] not in known]
    assert [r["question"] for r in created] == [QUESTION]
    assert created[0]["status"] == "queued"


def test_referral_lifecycle_writes_timeline_events(client):
    referral = _sent_referral(client)
    types = [(e["type"], e["payload"].get("referral_id")) for e in _timeline(client)]
    assert ("referral", referral["id"]) in types

    ack = client.post(f"/api/referrals/{referral['id']}/acknowledge", json={})
    assert ack.status_code == 200 and ack.json()["status"] == "acknowledged"
    done = client.post(f"/api/referrals/{referral['id']}/complete", json={"response_summary": "Seen, no change."})
    assert done.status_code == 200 and done.json()["status"] == "completed"
    assert done.json()["consult_event_id"]

    events = {e["type"]: e for e in _timeline(client) if e["payload"].get("referral_id") == referral["id"]}
    assert events["referral_update"]["payload"]["status"] == "acknowledged"
    assert events["referral_consult"]["payload"]["response_summary"] == "Seen, no change."
    # a completed referral cannot be acknowledged again
    assert client.post(f"/api/referrals/{referral['id']}/acknowledge", json={}).status_code == 400
    db = SessionLocal()
    try:
        assert db.scalar(select(Referral.status).where(Referral.id == referral["id"])) == "completed"
    finally:
        db.close()


def test_nurse_may_acknowledge_but_other_roles_may_not(client):
    referral = _sent_referral(client)
    url = f"/api/referrals/{referral['id']}/acknowledge"
    for headers in (PHARMACIST, BILLING, MGMT):
        assert client.post(url, json={}, headers=headers).status_code == 403
    response = client.post(url, json={}, headers=NURSE)
    assert response.status_code == 200
    assert response.json()["status"] == "acknowledged"


def test_only_clinical_roles_draft_and_only_a_doctor_approves(client):
    known = {r["id"] for r in _referrals(client)}
    assert client.post("/api/referrals/generate", json={"specialty": "Cardiology"}, headers=MGMT).status_code == 403
    assert client.post("/api/referrals/generate", json={"specialty": "Cardiology"}, headers=BILLING).status_code == 403
    draft = client.post(
        "/api/referrals/generate", json={"specialty": "Cardiology", "question": QUESTION}, headers=NURSE
    ).json()["draft"]
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={}, headers=NURSE).status_code == 403
    assert {r["id"] for r in _referrals(client)} == known
