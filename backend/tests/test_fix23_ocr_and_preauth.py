"""SPEC-023: confirmed OCR labs are unreviewed and raise alerts (F8); a pre-authorisation match needs the right document (F12).

PRD F8: "keeps the original, marks uncertain readings"; rule 3 and the F5 guardrail (an abnormal unreviewed result is an alert).
PRD F12: "checks completeness" - a lab report is not a pre-authorisation approval.
"""

from __future__ import annotations

from app.db import SessionLocal
from app.models import Document, DocumentRequest

from .helpers import text_pdf

DOCTOR = {"X-User-Id": "u_meera"}

CRITICAL = ["CITY LAB REPORT", "Collected: 03 Sep 2026 07:40", "Sodium 118 mmol/L (135-145)", "Potassium 6.8 mmol/L (3.5-5.1)"]


def _upload(client, lines, headers=None):
    response = client.post(
        "/api/documents/upload",
        files={"file": ("lab.pdf", text_pdf(lines), "application/pdf")},
        data={"doc_type": "lab_report"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _r3(client, status=None):
    rows = client.get("/api/alerts").json()["alerts"]
    return [a for a in rows if a["rule_id"] == "R3" and (status is None or a["status"] == status)]


def _commit_critical(client):
    doc = _upload(client, CRITICAL)  # a clean lab report is committed by the upload itself
    return doc, doc


def _add_document(doc_id, doc_type, patient_id="pat_ravi", status="reviewed"):
    db = SessionLocal()
    try:
        db.add(
            Document(
                id=doc_id,
                patient_id=patient_id,
                encounter_id=db.get(Document, "doc_seed_outside").encounter_id,
                filename=f"{doc_id}.pdf",
                mime="application/pdf",
                path="",
                image_kind="file",
                doc_type=doc_type,
                ocr_status=status,
                extracted={"fields": []},
            )
        )
        db.commit()
    finally:
        db.close()


def _prep(client):
    return client.get("/api/revenue/claim-prep").json()


def _pre_auth_present(prep):
    return next(d for d in prep["required_documents"] if d["key"] == "pre_auth")["present"]


def _request(request_id="req_seed_preauth"):
    db = SessionLocal()
    try:
        row = db.get(DocumentRequest, request_id)
        return row.status, row.matched_document_id
    finally:
        db.close()


# ---------- F8 ----------

def test_confirmed_ocr_labs_are_unreviewed_and_raise_r3_alerts_citing_the_lab_events(fresh):
    client = fresh
    before = {a["id"] for a in _r3(client)}
    _, body = _commit_critical(client)
    labs = {lab["payload"]["name"]: lab for lab in body["labs"]}
    assert set(labs) == {"Sodium", "Potassium"}
    assert [lab["payload"]["review_status"] for lab in labs.values()] == ["unreviewed", "unreviewed"]
    assert labs["Sodium"]["payload"]["flag"] == "low" and labs["Potassium"]["payload"]["flag"] == "high"

    invest = client.get("/api/investigations").json()
    unreviewed = {lab["name"]: lab for lab in invest["unreviewed"]}
    assert unreviewed["Sodium"]["event_id"] == labs["Sodium"]["id"]
    assert unreviewed["Potassium"]["event_id"] == labs["Potassium"]["id"]

    new = [a for a in _r3(client) if a["id"] not in before]
    by_title = {a["title"]: a for a in new}
    assert set(by_title) == {"Unreviewed abnormal result: Sodium", "Unreviewed abnormal result: Potassium"}
    assert by_title["Unreviewed abnormal result: Sodium"]["evidence_event_ids"] == [labs["Sodium"]["id"]]
    assert by_title["Unreviewed abnormal result: Potassium"]["evidence_event_ids"] == [labs["Potassium"]["id"]]
    assert {a["title"] for a in body["new_alerts"]} >= set(by_title)


def test_a_normal_confirmed_lab_is_unreviewed_but_raises_no_alert(client):
    before = {a["id"] for a in _r3(client)}
    doc = _upload(client, ["Sodium 140 mmol/L (135-145)"])
    assert doc["labs"][0]["payload"]["review_status"] == "unreviewed"
    assert doc["labs"][0]["payload"]["flag"] == "normal"
    assert [a for a in _r3(client) if a["id"] not in before] == []


def test_a_clinician_review_of_one_committed_lab_clears_only_that_alert(fresh):
    client = fresh
    _, body = _commit_critical(client)
    sodium = next(lab for lab in body["labs"] if lab["payload"]["name"] == "Sodium")
    reviewed = client.post(f"/api/labs/{sodium['id']}/review", headers=DOCTOR)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["event"]["payload"]["review_status"] == "reviewed"
    status = {a["title"]: a["status"] for a in _r3(client)}
    assert status["Unreviewed abnormal result: Sodium"] == "acknowledged"
    assert status["Unreviewed abnormal result: Potassium"] == "open"


def test_the_original_is_still_served_after_commit(client):
    doc, _ = _commit_critical(client)
    served = client.get(f"/api/documents/{doc['id']}/image")
    assert served.status_code == 200
    assert served.content == text_pdf(CRITICAL)
    assert served.headers["content-type"].startswith("application/pdf")


def test_low_confidence_fields_still_block_commit_and_raise_no_alert_until_confirmed(client):
    before = {a["id"] for a in _r3(client)}
    doc = _upload(client, ["Sodium 118 (135-145)"])  # no unit: confidence under 0.8
    assert doc["extracted"]["fields"][0]["confidence"] < 0.8
    refused = client.post(f"/api/documents/{doc['id']}/commit")
    assert refused.status_code == 400 and "Sodium" in refused.json()["detail"]
    assert [a for a in _r3(client) if a["id"] not in before] == []
    assert client.post(f"/api/documents/{doc['id']}/confirm-field", json={"index": 0, "value": "118"}).status_code == 200
    done = client.post(f"/api/documents/{doc['id']}/commit")
    assert done.status_code == 200, done.text
    assert done.json()["labs"][0]["payload"]["review_status"] == "unreviewed"
    assert [a["title"] for a in _r3(client) if a["id"] not in before] == ["Unreviewed abnormal result: Sodium"]


# ---------- F12 ----------

def test_match_refuses_a_lab_report_for_a_pre_authorisation_request(client):
    before = _request()
    assert _pre_auth_present(_prep(client)) is False
    refused = client.post("/api/document-requests/req_seed_preauth/match", json={"document_id": "doc_seed_outside"})
    assert refused.status_code == 400
    assert "pre-authorisation" in refused.json()["detail"] and "lab report" in refused.json()["detail"]
    assert _request() == before
    assert _pre_auth_present(_prep(client)) is False


def test_match_refuses_another_patients_document(client):
    _add_document("doc_other_patient_preauth", "pre_auth", patient_id="pat_joseph")
    refused = client.post(
        "/api/document-requests/req_seed_preauth/match", json={"document_id": "doc_other_patient_preauth"}
    )
    assert refused.status_code == 400
    assert "another patient" in refused.json()["detail"]
    assert _pre_auth_present(_prep(client)) is False


def test_a_matched_pre_authorisation_document_completes_the_requirement(client):
    _add_document("doc_test_preauth_ok", "pre_auth")
    matched = client.post("/api/document-requests/req_seed_preauth/match", json={"document_id": "doc_test_preauth_ok"})
    assert matched.status_code == 200, matched.text
    assert _request() == ("matched", "doc_test_preauth_ok")
    prep = _prep(client)
    assert _pre_auth_present(prep) is True
    assert "Pre-authorization approval" not in [d["label"] for d in prep["missing_documents"]]


def test_claims_ignore_a_matched_request_whose_document_is_not_a_pre_authorisation(client):
    """Legacy data: a request already marked matched to a lab report must not complete the requirement."""
    db = SessionLocal()
    try:
        row = db.get(DocumentRequest, "req_seed_preauth")
        row.status, row.matched_document_id = "matched", "doc_seed_outside"
        db.commit()
    finally:
        db.close()
    assert _pre_auth_present(_prep(client)) is False
    # a matched request with no document at all does not count either
    db = SessionLocal()
    try:
        db.get(DocumentRequest, "req_seed_preauth").matched_document_id = None
        db.commit()
    finally:
        db.close()
    assert _pre_auth_present(_prep(client)) is False


def test_only_a_confirmed_or_reviewed_pre_authorisation_document_counts_on_its_own(client):
    _add_document("doc_preauth_unconfirmed", "pre_auth", status="needs_confirmation")
    assert _pre_auth_present(_prep(client)) is False
    _add_document("doc_preauth_confirmed", "pre_auth", status="confirmed")
    assert _pre_auth_present(_prep(client)) is True
