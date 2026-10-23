"""T4b: a clean lab report is saved to the timeline by the upload itself, still unreviewed.

Only lab reports whose every field is read at 0.8 or above (ocr_status "reviewed") are saved without a
click. Low-confidence scans, scans with no text, prescriptions, radiology and discharge summaries stop
where they always did. No AI key is used: the text-layer reader and mocks only.
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.models import AuditEntry

from .helpers import text_pdf

DOCTOR = {"X-User-Id": "u_meera"}
PNG = b"\x89PNG\r\n\x1a\n"

CRITICAL = ["CITY LAB REPORT", "Collected: 03 Sep 2026 07:40", "Sodium 118 mmol/L (135-145)", "Potassium 6.8 mmol/L (3.5-5.1)"]
NORMAL = ["Sodium 140 mmol/L (135-145)"]
NO_UNIT = ["Sodium 118 (135-145)"]  # no unit: confidence 0.7

NEW_KEYS = {"auto_committed", "auto_commit_error", "labs", "events", "new_alerts"}
OLD_KEYS = {
    "id", "filename", "mime", "doc_type", "ocr_status", "raw_text", "extracted", "uploaded_by",
    "uploaded_at", "confirmed_by", "confirmed_at", "image_url",
}


def upload(client, content, doc_type="lab_report", name="report.pdf", mime="application/pdf"):
    response = client.post(
        "/api/documents/upload",
        files={"file": (name, content, mime)},
        data={"doc_type": doc_type},
        headers=DOCTOR,
    )
    assert response.status_code == 200, response.text
    return response.json()


def lab_upload(client, lines):
    return upload(client, text_pdf(lines))


def events_of(client, doc_id, types=None):
    url = "/api/patients/pat_ravi/timeline?limit=500" + (f"&types={types}" if types else "")
    return [e for e in client.get(url).json()["events"] if e.get("payload", {}).get("document_id") == doc_id]


def r3(client):
    return [a for a in client.get("/api/alerts").json()["alerts"] if a["rule_id"] == "R3"]


def audit_of(client, doc_id):
    return client.get(f"/api/audit/{doc_id}").json()["audit"]


def balance(client):
    return client.get("/api/credits").json()["balance"]


# ---------- the clean lab report is saved, and a doctor must still review it ----------

def test_clean_abnormal_lab_is_saved_without_a_click_and_raises_r3(fresh):
    client = fresh
    before = {a["id"] for a in r3(client)}
    doc = lab_upload(client, CRITICAL)

    assert doc["auto_committed"] is True and doc["auto_commit_error"] is None
    assert doc["ocr_status"] == "confirmed" and doc["confirmed_by"] == "system (auto)" and doc["confirmed_at"]
    events = events_of(client, doc["id"], "lab_result")
    by_name = {e["payload"]["name"]: e for e in events}
    assert set(by_name) == {"Sodium", "Potassium"}
    assert {e["payload"]["review_status"] for e in events} == {"unreviewed"}
    assert by_name["Sodium"]["payload"]["flag"] == "low" and by_name["Potassium"]["payload"]["flag"] == "high"
    assert all(e["author_type"] == "system" and e["author_name"] == "system (auto)" for e in events)

    # the response carries what the Labs tab needs: the new rows and the alerts
    assert {e["id"] for e in doc["labs"]} == {e["id"] for e in events} and doc["events"] == doc["labs"]
    new = {a["id"]: a for a in r3(client) if a["id"] not in before}
    assert {a["title"] for a in new.values()} == {
        "Unreviewed abnormal result: Sodium", "Unreviewed abnormal result: Potassium"}
    assert {a["title"] for a in doc["new_alerts"]} >= {a["title"] for a in new.values()}
    by_title = {a["title"]: a for a in new.values()}
    assert by_title["Unreviewed abnormal result: Sodium"]["evidence_event_ids"] == [by_name["Sodium"]["id"]]

    unreviewed = {lab["name"]: lab for lab in client.get("/api/investigations").json()["unreviewed"]}
    assert unreviewed["Sodium"]["event_id"] == by_name["Sodium"]["id"]
    assert client.get(f"/api/documents/{doc['id']}").json()["ocr_status"] == "confirmed"


def test_clean_normal_lab_is_saved_unreviewed_with_no_alert(client):
    before = {a["id"] for a in r3(client)}
    doc = lab_upload(client, NORMAL)
    assert doc["auto_committed"] is True
    assert [e["payload"]["review_status"] for e in doc["labs"]] == ["unreviewed"]
    assert doc["labs"][0]["payload"]["flag"] == "normal"
    assert [a for a in r3(client) if a["id"] not in before] == []


def test_a_doctor_review_clears_only_that_labs_alert(fresh):
    client = fresh
    doc = lab_upload(client, CRITICAL)
    sodium = next(lab for lab in doc["labs"] if lab["payload"]["name"] == "Sodium")
    reviewed = client.post(f"/api/labs/{sodium['id']}/review", headers=DOCTOR)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["event"]["payload"]["review_status"] == "reviewed"
    status = {a["title"]: a["status"] for a in r3(client)}
    assert status["Unreviewed abnormal result: Sodium"] == "acknowledged"
    assert status["Unreviewed abnormal result: Potassium"] == "open"


# ---------- audit ----------

def test_audit_has_one_system_entry_for_the_auto_commit_and_no_confirmation(client):
    doc = lab_upload(client, CRITICAL)
    entries = audit_of(client, doc["id"])
    auto = [e for e in entries if e["action"] == "document_auto_committed"]
    assert len(auto) == 1
    assert auto[0]["actor_type"] == "system" and auto[0]["actor_name"] == "system (auto)"
    assert auto[0]["entity_type"] == "document" and auto[0]["entity_id"] == doc["id"]
    assert set(auto[0]["after"]["events_created"]) == {e["id"] for e in doc["labs"]}
    assert auto[0]["meta"]["trigger"] == "upload"
    assert not [e for e in entries if e["action"] == "document_confirmed"]
    for event in doc["labs"]:
        committed = [e for e in audit_of(client, event["id"]) if e["action"] == "timeline_committed"]
        assert len(committed) == 1 and committed[0]["actor_name"] == "system (auto)"
        assert committed[0]["actor_type"] == "system"


def test_manual_commit_after_auto_commit_is_refused_and_adds_nothing(client):
    doc = lab_upload(client, CRITICAL)
    count, audits = len(events_of(client, doc["id"])), len(audit_of(client, doc["id"]))
    assert client.post(f"/api/documents/{doc['id']}/commit", headers=DOCTOR).status_code == 409
    assert len(events_of(client, doc["id"])) == count == 2
    assert len(audit_of(client, doc["id"])) == audits


def test_manual_commit_still_writes_the_human_confirmation_entry(client):
    doc = upload(client, text_pdf(NO_UNIT))
    assert client.post(f"/api/documents/{doc['id']}/confirm-field", json={"index": 0, "value": "118"}, headers=DOCTOR).status_code == 200
    done = client.post(f"/api/documents/{doc['id']}/commit", headers=DOCTOR)
    assert done.status_code == 200, done.text
    actions = [e["action"] for e in audit_of(client, doc["id"])]
    assert "document_confirmed" in actions and "document_auto_committed" not in actions
    confirmed = next(e for e in audit_of(client, doc["id"]) if e["action"] == "document_confirmed")
    assert confirmed["actor_name"] != "system (auto)" and confirmed["actor_type"] == "user"
    assert all(e["author_type"] == "human" for e in events_of(client, doc["id"]))


# ---------- everything else stops where it always did ----------

def test_low_confidence_scan_creates_no_events_until_a_human_confirms(client):
    before = {a["id"] for a in r3(client)}
    doc = upload(client, text_pdf(NO_UNIT))
    assert doc["ocr_status"] == "needs_confirmation" and doc["auto_committed"] is False
    assert doc["labs"] == [] and doc["events"] == [] and doc["new_alerts"] == []
    assert events_of(client, doc["id"]) == [] and [a for a in r3(client) if a["id"] not in before] == []
    assert client.post(f"/api/documents/{doc['id']}/commit", headers=DOCTOR).status_code == 400

    assert client.post(f"/api/documents/{doc['id']}/confirm-field", json={"index": 0, "value": "118"}, headers=DOCTOR).status_code == 200
    assert client.get(f"/api/documents/{doc['id']}").json()["ocr_status"] == "reviewed"
    assert events_of(client, doc["id"]) == []  # confirming a field is not an upload: still a manual save
    assert client.post(f"/api/documents/{doc['id']}/commit", headers=DOCTOR).status_code == 200
    assert len(events_of(client, doc["id"], "lab_result")) == 1


def test_scan_with_no_text_is_not_committed(client):
    doc = upload(client, PNG, name="scan.png", mime="image/png")
    assert doc["ocr_status"] == "needs_manual_entry" and doc["auto_committed"] is False
    assert events_of(client, doc["id"]) == []


@pytest.mark.parametrize(
    "doc_type, lines, event_type",
    [
        ("prescription", ["Metformin 500 mg twice daily", "Atorvastatin 20 mg at night"], "med_order"),
        ("radiology_report", ["Findings: Clear lung fields.", "Impression: No acute disease."], "document_review"),
        ("discharge_summary", ["Diagnosis: Community acquired pneumonia", "Conclusion: Improved"], "document_review"),
    ],
)
def test_other_document_types_never_auto_commit(client, doc_type, lines, event_type):
    home_before = client.get("/api/patients/pat_ravi/state").json()["home_meds"]
    doc = upload(client, text_pdf(lines), doc_type)
    assert doc["ocr_status"] == "reviewed" and doc["auto_committed"] is False
    assert doc["labs"] == [] and doc["events"] == [] and doc["new_alerts"] == []
    assert events_of(client, doc["id"]) == []
    assert client.get("/api/patients/pat_ravi/state").json()["home_meds"] == home_before
    assert not [e for e in audit_of(client, doc["id"]) if e["action"] == "document_auto_committed"]
    done = client.post(f"/api/documents/{doc['id']}/commit", headers=DOCTOR)
    assert done.status_code == 200, done.text
    assert events_of(client, doc["id"], event_type)


def test_confidence_boundary_is_zero_point_eight(client, monkeypatch):
    def fake(fields):
        def parse_report(doc_type, pages, fallback_date):
            return {"document_type": doc_type, "fields": fields, "raw_text": "x"}
        return parse_report

    def field(name, confidence):
        return {"name": name, "value": "1.0", "unit": "mg/dL", "reference_range": "0.5-1.5",
                "collected_at": "2026-09-03", "confidence": confidence, "page": 1}

    monkeypatch.setattr("app.services.ocr.parse_report", fake([field("A", 0.8), field("B", 0.95)]))
    clean = lab_upload(client, NORMAL)
    assert clean["auto_committed"] is True and len(clean["labs"]) == 2

    monkeypatch.setattr("app.services.ocr.parse_report", fake([field("A", 0.8), field("B", 0.79)]))
    held = lab_upload(client, NORMAL)
    assert held["ocr_status"] == "needs_confirmation" and held["auto_committed"] is False
    assert events_of(client, held["id"]) == []


# ---------- credits and failure ----------

def test_credits_are_charged_once_exactly_as_before(client):
    start = balance(client)
    lab_upload(client, CRITICAL)
    assert balance(client) == start - 1
    ledger = client.get("/api/credits").json()["ledger"]
    assert [(e["operation"], e["units"], e["feature"]) for e in ledger[:1]] == [("report_reading", 1, "F8")]
    assert len([e for e in ledger if e["operation"] == "report_reading"]) == 1


def test_a_failed_auto_commit_leaves_the_upload_intact(client, monkeypatch):
    start = balance(client)

    def boom(*args, **kwargs):
        raise RuntimeError("rules engine unavailable")

    monkeypatch.setattr("app.routes.documents._commit_and_evaluate", boom)
    doc = lab_upload(client, CRITICAL)
    assert doc["auto_committed"] is False and "rules engine unavailable" in doc["auto_commit_error"]
    assert doc["ocr_status"] == "reviewed" and doc["labs"] == [] and len(doc["extracted"]["fields"]) == 2
    assert events_of(client, doc["id"]) == []
    assert balance(client) == start - 1
    failed = [e for e in audit_of(client, doc["id"]) if e["action"] == "document_auto_commit_failed"]
    assert len(failed) == 1 and failed[0]["actor_name"] == "system (auto)"
    monkeypatch.undo()
    assert client.post(f"/api/documents/{doc['id']}/commit", headers=DOCTOR).status_code == 200


def test_a_half_written_auto_commit_is_rolled_back(client, monkeypatch):
    """The rules re-run fails after the events were added: no events remain."""
    def boom(*args, **kwargs):
        raise RuntimeError("rules failed")

    monkeypatch.setattr("app.routes.documents.evaluate_rules", boom)
    doc = lab_upload(client, CRITICAL)
    assert doc["auto_committed"] is False and doc["ocr_status"] == "reviewed"
    assert events_of(client, doc["id"]) == []
    with SessionLocal() as db:
        actions = [a.action for a in db.query(AuditEntry).filter(AuditEntry.entity_id == doc["id"])]
    assert "document_auto_committed" not in actions and "timeline_committed" not in actions


# ---------- compatibility ----------

@pytest.mark.parametrize("kind", ["clean", "low", "image", "rx"])
def test_upload_response_keeps_old_keys_and_always_has_the_new_ones(client, kind):
    doc = {
        "clean": lambda: lab_upload(client, NORMAL),
        "low": lambda: lab_upload(client, NO_UNIT),
        "image": lambda: upload(client, PNG, name="s.png", mime="image/png"),
        "rx": lambda: upload(client, text_pdf(["Metformin 500 mg twice daily"]), "prescription"),
    }[kind]()
    assert OLD_KEYS <= set(doc) and NEW_KEYS <= set(doc)
    assert isinstance(doc["labs"], list) and isinstance(doc["events"], list) and isinstance(doc["new_alerts"], list)
    assert isinstance(doc["auto_committed"], bool)


def test_document_list_shows_the_auto_committed_document_as_confirmed(client):
    doc = lab_upload(client, NORMAL)
    listed = {d["id"]: d for d in client.get("/api/documents").json()["documents"]}
    assert listed[doc["id"]]["ocr_status"] == "confirmed" and listed[doc["id"]]["confirmed_by"] == "system (auto)"
    assert listed["doc_seed_outside"]["ocr_status"] == "needs_confirmation"
