"""Shared plumbing: roles, patient scope, credits, background jobs, encounter lock."""

from __future__ import annotations

import pytest

from app import background
from app.db import SessionLocal
from app.services import credits

from .helpers import SHORT_VISIT, discharge, generate_note

DOCTOR, NURSE, PHARMACIST, BILLING, MGMT = "u_meera", "u_anita", "u_dev", "u_billing", "u_mgmt"


def as_user(user_id: str) -> dict:
    return {"X-User-Id": user_id}


# ---------- roles ----------

def test_default_user_is_the_attending_physician(client):
    me = client.get("/api/meta").json()
    assert me["user"]["role"] == "doctor"
    assert me["demo_user"] == "Dr. Meera Shah"


def test_unknown_user_is_rejected(client):
    assert client.get("/api/meta", headers=as_user("u_nobody")).status_code == 400


def test_meta_reports_what_the_user_may_do(client):
    nurse = client.get("/api/meta", headers=as_user(NURSE)).json()
    assert "give_medicine" in nurse["allowed_actions"]
    assert "approve_draft" not in nurse["allowed_actions"]


def test_nurse_cannot_approve_a_draft(client):
    draft = client.post("/api/referrals/generate", json={}, headers=as_user(DOCTOR))
    draft_id = (draft.json() if draft.status_code == 200 else generate_note(client, "F3", SHORT_VISIT + "\nDoctor: check bloods."))
    draft_id = draft_id["draft"]["id"] if "draft" in draft_id else draft_id["id"]
    response = client.post(f"/api/drafts/{draft_id}/approve", json={}, headers=as_user(NURSE))
    assert response.status_code == 403


def test_management_is_read_only(client):
    assert client.get("/api/hospital/dashboard", headers=as_user(MGMT)).status_code == 200
    assert client.post("/api/tasks", json={"title": "Not allowed"}, headers=as_user(MGMT)).status_code == 403


def test_nurse_can_create_and_pharmacist_cannot_dismiss_alerts(client):
    assert client.post("/api/tasks", json={"title": "Nurse task"}, headers=as_user(NURSE)).status_code == 200
    alert = client.get("/api/alerts").json()["alerts"][0]
    body = {"reason": "Reviewed and accepted by the team", "category": "known_and_accepted"}
    assert client.post(f"/api/alerts/{alert['id']}/dismiss", json=body, headers=as_user(PHARMACIST)).status_code == 403


def test_billing_works_on_claims_only(client):
    assert client.post("/api/revenue/claim-prep/explain", headers=as_user(BILLING)).status_code == 200
    note = generate_note(client, "F4", SHORT_VISIT)
    assert client.post(f"/api/drafts/{note['id']}/approve", json={}, headers=as_user(BILLING)).status_code == 403


def test_acting_user_is_recorded_not_taken_from_the_request_body(client):
    task = client.post("/api/tasks", json={"title": "Who made this"}, headers=as_user(NURSE)).json()
    audit = client.get("/api/audit").json()["audit"]
    created = [e for e in audit if e["action"] == "task_created" and e["entity_id"] == task["id"]]
    assert created and created[0]["actor_name"] == "Nurse Anita Rao"


# ---------- patient scope ----------

def test_patient_header_changes_who_the_app_shows(client):
    meta = client.get("/api/meta", headers={"X-Patient-Id": "pat_anita"}).json()
    assert meta["patient"]["id"] == "pat_anita"
    assert meta["encounter"]["id"] != "enc_ipd_1"


def test_patient_list_includes_the_cohort(client):
    ids = {p["id"] for p in client.get("/api/patients").json()["patients"]}
    assert {"pat_ravi", "pat_anita", "pat_arun", "pat_joseph", "pat_meera"} <= ids


def test_unknown_patient_is_a_clear_error(client):
    assert client.get("/api/meta", headers={"X-Patient-Id": "pat_nobody"}).status_code == 400


# ---------- credits ----------

def test_credit_pack_starts_full_and_resets(client):
    state = client.get("/api/credits").json()
    assert state["balance"] == state["pack_size"] == 5000
    assert state["schedule"] == {
        "report_reading": 1, "voice_note": 2, "medicine_reconciliation": 2, "report_analysis": 4, "discharge_summary": 5,
    }
    db = SessionLocal()
    try:
        credits.charge(db, "discharge_summary", feature="F9")
        db.commit()
    finally:
        db.close()
    after = client.get("/api/credits").json()
    assert after["balance"] == 4995 and after["ledger"][0]["operation"] == "discharge_summary"
    client.post("/api/demo/reset?mode=rehearsal")
    assert client.get("/api/credits").json()["balance"] == 5000


def test_exhausted_pack_blocks_the_operation():
    db = SessionLocal()
    try:
        credits.reset(db)
        account = credits._account(db)
        account.balance = 1
        db.flush()
        with pytest.raises(credits.CreditsExhausted):
            credits.charge(db, "discharge_summary")
        db.rollback()
    finally:
        db.close()


def test_only_billing_can_add_a_pack(client):
    assert client.post("/api/credits/packs", json={"size": 15000}, headers=as_user(NURSE)).status_code == 403
    result = client.post("/api/credits/packs", json={"size": 15000}, headers=as_user(BILLING))
    assert result.status_code == 200 and result.json()["balance"] == 20000
    assert client.post("/api/credits/packs", json={"size": 7}, headers=as_user(BILLING)).status_code == 400


# ---------- background jobs ----------

def test_registered_jobs_run_on_demand():
    calls = []
    background.register("test-job", lambda db: calls.append("ran") or "done", 60)
    try:
        assert background.run_job("test-job") == "done"
        assert calls == ["ran"]
    finally:
        background.JOBS.pop("test-job", None)


# ---------- encounter lock ----------

def test_clinical_writes_stop_after_discharge_but_claim_work_continues(client):
    assert discharge(client, override={"reason": "Test discharge with open alerts"}).status_code == 200
    assert client.post("/api/notes/generate", json={"feature": "F4", "transcript": SHORT_VISIT}).status_code == 409
    assert client.post("/api/tasks", json={"title": "Too late"}).status_code == 409
    assert client.post("/api/revenue/claim-prep/explain").status_code == 200
