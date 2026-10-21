"""SPEC-020: medicine decisions reach discharge readiness and the dashboard; the print page is per patient.

PRD journey stage 4 "Medicines reconciled (F6)"; PRD F14 "discrepancies for management"; PRD rule 2
(printed summary holds only documented content).
"""

from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Alert, AuditEntry, Draft, Task

from .helpers import discharge, inject_event

REASON = "Reviewed with the team before discharge"
PHARMACIST = {"X-User-Id": "u_dev"}
NOTE = "Decided after checking the chart"


def _differences(client, **headers) -> list[dict]:
    return client.get("/api/discharge/readiness", headers=headers).json()["warnings"]["unresolved_medicine_differences"]


def _recon_ids(client) -> list[str]:
    body = client.get("/api/medications/reconciliation").json()
    return [item["id"] for item in body["discrepancies"] if item["status"] == "open"]


def _resolve(client, discrepancy_id: str):
    return client.post(
        f"/api/medications/reconciliation/{discrepancy_id}/resolve",
        json={"decision": "continue", "note": NOTE},
        headers=PHARMACIST,
    )


def _clear_alerts_and_tasks() -> None:
    """Leave medicine differences as the only warning on the record."""
    db = SessionLocal()
    try:
        for alert in db.scalars(select(Alert).where(Alert.patient_id == "pat_ravi")):
            alert.status = "dismissed"
        for task in db.scalars(select(Task).where(Task.patient_id == "pat_ravi")):
            task.status = "completed"
        db.commit()
    finally:
        db.close()


def _row(data: dict, patient_id: str) -> dict:
    return next(row for row in data["patients"] if row["patient_id"] == patient_id)


# ---------- readiness ----------

def test_readiness_lists_unresolved_medicine_differences_and_ready_is_unchanged(client):
    ids = _recon_ids(client)
    assert len(ids) >= 3
    body = client.get("/api/discharge/readiness").json()
    listed = body["warnings"]["unresolved_medicine_differences"]
    assert [item["id"] for item in listed] == ids
    assert all(set(item) == {"id", "title"} and item["title"] for item in listed)
    assert any(item["title"].startswith("Metformin") for item in listed)
    assert body["ready"] is True  # required documentation only


def test_approval_without_override_is_409_and_names_the_medicine_differences(client):
    titles = [item["title"] for item in _differences(client)]
    response = discharge(client)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "unresolved medicine differences" in detail
    assert all(title in detail for title in titles)


def test_differences_alone_need_a_reason_of_ten_characters_and_are_audited(client):
    _clear_alerts_and_tasks()
    body = client.get("/api/discharge/readiness").json()
    assert body["warnings"]["open_critical_alerts"] == [] and body["warnings"]["open_tasks"] == []
    assert body["needs_override"] is True
    ids = [item["id"] for item in body["warnings"]["unresolved_medicine_differences"]]
    assert ids
    response = discharge(client)
    assert response.status_code == 409
    assert "unresolved medicine differences" in response.json()["detail"]
    assert "open critical alerts" not in response.json()["detail"]
    assert discharge(client, override={"reason": "too short"}).status_code == 409
    ok = discharge(client, override={"reason": REASON})
    assert ok.status_code == 200, ok.text
    db = SessionLocal()
    try:
        entries = list(db.scalars(select(AuditEntry).where(AuditEntry.action == "discharge_override")))
    finally:
        db.close()
    assert len(entries) == 1
    assert [d["id"] for d in entries[0].after["unresolved_medicine_differences"]] == ids


def test_deciding_every_difference_removes_them_from_the_warnings(client):
    _clear_alerts_and_tasks()
    ids = _recon_ids(client)
    assert _resolve(client, ids[0]).status_code == 200
    remaining = [item["id"] for item in _differences(client)]
    assert remaining == ids[1:]
    for discrepancy_id in ids[1:]:
        assert _resolve(client, discrepancy_id).status_code == 200
    assert _differences(client) == []
    body = client.get("/api/discharge/readiness").json()
    assert body["needs_override"] is False and body["ready"] is True
    response = discharge(client)  # no override needed any more
    assert response.status_code == 200, response.text


def test_decided_differences_are_not_named_in_the_409(client):
    ids = _recon_ids(client)
    decided = next(item for item in _differences(client) if item["id"] == ids[0])
    assert _resolve(client, ids[0]).status_code == 200
    detail = discharge(client).json()["detail"]
    assert decided["title"] not in detail
    assert "unresolved medicine differences" in detail


def test_a_record_without_home_medicines_has_no_medicine_warning(fresh):
    body = fresh.get("/api/discharge/readiness").json()
    assert body["warnings"]["unresolved_medicine_differences"] == []


# ---------- dashboard ----------

def test_deciding_a_difference_lowers_the_dashboard_row_and_summary_by_one(client):
    before = client.get("/api/hospital/dashboard").json()
    ravi_before = _row(before, "pat_ravi")["medicine_discrepancies"]
    assert ravi_before >= 3
    assert _resolve(client, _recon_ids(client)[0]).status_code == 200
    for headers in ({}, {"X-Patient-Id": "pat_joseph"}):
        after = client.get("/api/hospital/dashboard", headers=headers).json()
        assert _row(after, "pat_ravi")["medicine_discrepancies"] == ravi_before - 1
        assert after["summary"]["medicine_discrepancies"] == before["summary"]["medicine_discrepancies"] - 1
        for patient_id in ("pat_anita", "pat_joseph", "pat_meera", "pat_arun"):
            assert _row(after, patient_id)["medicine_discrepancies"] == _row(before, patient_id)["medicine_discrepancies"]


# ---------- print page ----------

def _print(client, draft_id: str, **headers):
    return client.get(f"/api/discharge/{draft_id}/print", headers=headers)


def test_print_page_shows_the_real_patient_and_escapes_text(client):
    draft = client.post("/api/discharge/generate").json()["draft"]
    db = SessionLocal()
    try:
        row = db.get(Draft, draft["id"])
        row.content = {
            "sections": [
                {
                    "heading": "Course <script>alert(1)</script>",
                    "paragraphs": [{"text": "Took <script>alert('x')</script> & rested"}],
                }
            ],
            "medications": [
                {"drug": "<b>Drug</b>", "dose": "1 g", "route": "PO", "frequency": "BD", "safety_note": "<i>check</i>"}
            ],
        }
        db.commit()
    finally:
        db.close()
    response = _print(client, draft["id"])
    assert response.status_code == 200
    page = response.text
    assert "<script>" not in page and "<b>Drug</b>" not in page and "<i>check</i>" not in page
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; &amp; rested" in page
    assert "Course &lt;script&gt;" in page
    assert "Ravi Menon" in page and "MB-1001" in page


def test_print_page_is_not_hard_coded_to_ravi(client):
    headers = {"X-Patient-Id": "pat_joseph"}
    generated = client.post("/api/discharge/generate", headers=headers)
    assert generated.status_code == 200, generated.text
    draft_id = generated.json()["draft"]["id"]
    patient = client.get("/api/patients/pat_joseph/timeline").json()
    joseph = next(r for r in client.get("/api/hospital/dashboard").json()["patients"] if r["patient_id"] == "pat_joseph")
    assert patient["count"] > 0
    for header in ({}, headers, {"X-Patient-Id": "pat_ravi"}):
        page = _print(client, draft_id, **header).text
        assert joseph["name"] in page and joseph["mrn"] in page
        assert "Ravi Menon" not in page and "MB-1001" not in page


def test_print_of_an_unknown_draft_is_404(client):
    assert _print(client, "drf_does_not_exist").status_code == 404


def test_a_queued_referral_still_counts_as_open_on_the_dashboard(client):
    from app.models import Referral

    before = client.get("/api/hospital/dashboard").json()
    db = SessionLocal()
    try:
        db.add(Referral(id="ref_fix20_queued", patient_id="pat_ravi", encounter_id="enc_ipd_1", specialty="Nephrology", status="queued"))
        db.commit()
    finally:
        db.close()
    try:
        after = client.get("/api/hospital/dashboard").json()
        assert _row(after, "pat_ravi")["open_referrals"] == _row(before, "pat_ravi")["open_referrals"] + 1
        assert after["summary"]["open_referrals"] == before["summary"]["open_referrals"] + 1
    finally:
        db = SessionLocal()
        try:
            db.delete(db.get(Referral, "ref_fix20_queued"))
            db.commit()
        finally:
            db.close()
