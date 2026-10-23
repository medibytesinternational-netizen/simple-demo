"""F10: pre-filled investigation and radiology request (PRD: indication, diagnosis and allergies to verify)."""

from __future__ import annotations

from datetime import datetime

from tests.helpers import ASTHMA, generate_note, inject_lab, joined

GEN = "/api/investigation-requests/generate"


def _approved_request(client, body=None) -> dict:
    draft = client.post(GEN, json=body).json()["draft"] if body else client.post(GEN).json()["draft"]
    for item in draft["content"]["allergies_to_verify"]:
        assert client.post(f"/api/drafts/{draft['id']}/verify-allergy", json={"substance": item["substance"]}).status_code == 200
    approved = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert approved.status_code == 200, approved.text
    requests = client.get("/api/investigation-requests").json()["requests"]
    return next(r for r in requests if r["draft_id"] == draft["id"])


def test_generation_works_on_the_rehearsal_record_with_dict_allergies(client):
    response = client.post(GEN)
    assert response.status_code == 200, response.text
    content = response.json()["draft"]["content"]
    assert content["study"] == "Renal ultrasound"
    assert content["request_type"] == "imaging"
    assert content["allergies_to_verify"] == [
        {"substance": "Penicillin", "reaction": "rash", "source_event_id": "evt_seed_allergy", "verified": False}
    ]
    source = client.get(f"/api/events/{content['allergies_to_verify'][0]['source_event_id']}").json()
    assert source["type"] == "allergy_record"
    assert source["payload"]["substance"] == "Penicillin"


def test_inferred_renal_study_cites_real_result_event_ids(client):
    content = client.post(GEN).json()["draft"]["content"]
    text = content["indication"]["text"]
    assert text.startswith("Abnormal results: ")
    assert "eGFR 22 mL/min/1.73m² (low)" in text
    assert "Creatinine 2.9 mg/dL (high)" in text
    cited = content["indication"]["source_event_ids"]
    assert "evt_seed_lab_egfr" in cited and "evt_seed_lab_creatinine" in cited
    for event_id in cited:
        event = client.get(f"/api/events/{event_id}").json()
        assert event["type"] == "lab_result"
    assert content["diagnosis"] == "Type 2 diabetes, Hypertension, CKD stage 3b, Atrial fibrillation"
    assert content["source_event_ids"] == cited


def test_a_supplied_study_is_honoured(client):
    xray = client.post(GEN, json={"study": "Chest X-ray"}).json()["draft"]["content"]
    assert (xray["study"], xray["request_type"]) == ("Chest X-ray", "imaging")
    lab = client.post(GEN, json={"study": "HbA1c"}).json()["draft"]["content"]
    assert (lab["study"], lab["request_type"]) == ("HbA1c", "laboratory")
    forced = client.post(GEN, json={"study": "Chest X-ray", "request_type": "laboratory"}).json()["draft"]["content"]
    assert forced["request_type"] == "laboratory"


def test_unknown_request_type_is_refused(client):
    assert client.post(GEN, json={"study": "Chest X-ray", "request_type": "surgery"}).status_code == 422


def test_other_abnormal_results_give_a_repeat_laboratory_request(fresh):
    lab_id = inject_lab("CRP", "40", "mg/L", "0 - 5", "high", datetime(2026, 10, 20, 6, 0))
    content = fresh.post(GEN).json()["draft"]["content"]
    assert content["study"] == "Repeat CRP"
    assert content["request_type"] == "laboratory"
    assert content["indication"]["source_event_ids"] == [lab_id]
    assert content["indication"]["text"] == "Abnormal results: CRP 40 mg/L (high)"


def test_empty_record_needs_a_study(fresh):
    response = fresh.post(GEN)
    assert response.status_code == 422
    assert response.json()["detail"] == "Choose the study to request"
    assert fresh.get("/api/drafts?feature=F10").json()["drafts"] == []


def test_empty_record_with_a_study_invents_no_indication(fresh):
    response = fresh.post(GEN, json={"study": "Chest X-ray"})
    assert response.status_code == 200, response.text
    content = response.json()["draft"]["content"]
    assert content["study"] == "Chest X-ray"
    assert content["indication"]["text"] == ""
    assert content["indication"]["source_event_ids"] == []
    assert content["source_event_ids"] == []
    assert content["instructions"] == ""
    text = joined({k: content[k] for k in ("indication", "instructions")})
    for fixed in ("egfr", "creatinine", "ckd", "renal", "22", "2.9"):
        assert fixed not in text
    # The start record holds no allergy record event, so no source id is invented.
    assert content["allergies_to_verify"] == [
        {"substance": "Penicillin", "reaction": "rash", "source_event_id": "", "verified": False}
    ]


def test_approval_is_blocked_until_the_allergy_is_verified(client):
    draft = client.post(GEN).json()["draft"]
    blocked = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert blocked.status_code == 400
    assert "Penicillin" in blocked.json()["detail"]
    before = client.get("/api/investigation-requests").json()["requests"]
    assert draft["id"] not in [r["draft_id"] for r in before]
    verified = client.post(f"/api/drafts/{draft['id']}/verify-allergy", json={"substance": "Penicillin"})
    assert verified.status_code == 200
    item = verified.json()["content"]["allergies_to_verify"][0]
    assert item["verified"] is True and item["verified_by"]
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={}).status_code == 200
    requests = client.get("/api/investigation-requests").json()["requests"]
    created = [r for r in requests if r["draft_id"] == draft["id"]]
    assert [(r["study"], r["status"]) for r in created] == [("Renal ultrasound", "approved")]


def test_unknown_allergies_are_refused(client):
    draft = client.post(GEN).json()["draft"]
    url = f"/api/drafts/{draft['id']}/verify-allergy"
    # The draft holds the split substance, not the patient's unsplit string.
    assert client.post(url, json={"substance": "Penicillin — rash"}).status_code == 404
    assert client.post(url, json={"substance": "Latex"}).status_code == 404


def test_allergy_verification_still_refuses_other_features(client):
    note = generate_note(client, "F1", ASTHMA)
    response = client.post(f"/api/drafts/{note['id']}/verify-allergy", json={"substance": "Penicillin"})
    assert response.status_code == 400


def test_export_marks_exported_and_audits(client):
    request = _approved_request(client)
    assert request["status"] == "approved"
    response = client.post(f"/api/investigation-requests/{request['id']}/export")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "exported" and body["exported_at"]
    entries = client.get(f"/api/audit/{request['id']}").json()["audit"]
    assert [e["action"] for e in entries].count("investigation_request_exported") == 1


def test_export_is_refused_for_unknown_and_already_exported_requests(client):
    request = _approved_request(client)
    assert client.post("/api/investigation-requests/inv_missing/export").status_code == 404
    assert client.post(f"/api/investigation-requests/{request['id']}/export").status_code == 200
    again = client.post(f"/api/investigation-requests/{request['id']}/export")
    assert again.status_code == 409
    assert "already" in again.json()["detail"]


def test_export_is_refused_for_a_request_that_is_not_approved(client):
    request = _approved_request(client)
    from app.db import SessionLocal
    from app.models import InvestigationRequest
    db = SessionLocal()
    try:
        db.get(InvestigationRequest, request["id"]).status = "draft"
        db.commit()
    finally:
        db.close()
    response = client.post(f"/api/investigation-requests/{request['id']}/export")
    assert response.status_code == 409
    assert response.json()["detail"] == "Only approved requests can be exported"


def test_an_approved_request_can_be_exported(client):
    request = _approved_request(client)
    url = f"/api/investigation-requests/{request['id']}/export"
    assert client.post(url).status_code == 200


def test_a_request_can_be_generated(client):
    assert client.post(GEN).status_code == 200

