"""Shared plumbing: identity, patient scope, credits, background jobs, encounter lock."""

from __future__ import annotations

import pytest

from app import background
from app.db import SessionLocal
from app.services import credits

from .helpers import SHORT_VISIT, discharge, generate_note

DOCTOR = "u_meera"


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
    me = client.get("/api/meta").json()
    allowed = set(me["allowed_actions"])
    assert {"give_medicine", "approve_draft", "buy_credits", "revenue_work", "order_medicine"} <= allowed
    assert "ingest" not in allowed  # the system link's action, not a person's


def test_acting_user_is_recorded_not_taken_from_the_request_body(client):
    task = client.post("/api/tasks", json={"title": "Who made this"}, headers=as_user(DOCTOR)).json()
    audit = client.get("/api/audit").json()["audit"]
    created = [e for e in audit if e["action"] == "task_created" and e["entity_id"] == task["id"]]
    assert created and created[0]["actor_name"] == "Dr. Meera Shah"


# ---------- patient scope ----------

def test_patient_header_for_a_cohort_patient_is_refused(client):
    assert client.get("/api/meta", headers={"X-Patient-Id": "pat_anita"}).status_code == 403
    assert client.get("/api/meta", headers={"X-Patient-Id": "pat_ravi"}).json()["patient"]["id"] == "pat_ravi"


def test_patient_list_is_ravi_only(client):
    ids = [p["id"] for p in client.get("/api/patients").json()["patients"]]
    assert ids == ["pat_ravi"]


def test_unknown_patient_is_a_clear_error(client):
    response = client.get("/api/meta", headers={"X-Patient-Id": "pat_nobody"})
    assert response.status_code == 403
    assert "pat_nobody" in response.json()["detail"]


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


def test_the_doctor_can_add_a_pack(client):
    result = client.post("/api/credits/packs", json={"size": 15000}, headers=as_user(DOCTOR))
    assert result.status_code == 200 and result.json()["balance"] == 20000
    assert client.post("/api/credits/packs", json={"size": 7}, headers=as_user(DOCTOR)).status_code == 400


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
