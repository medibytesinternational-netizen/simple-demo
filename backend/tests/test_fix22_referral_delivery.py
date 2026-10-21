"""PRD rules 4 and 5: a referral is "sent" only when the hospital system accepted it (2xx).

Until then it is "queued" with no sent_at, so the referral row and /api/integrations/status agree.
The mock hospital is the stdlib server of test_s17_integration (127.0.0.1, port chosen by the OS).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import SessionLocal, utcnow
from app.models import Referral
from app.models_ext.s17_integration import OutboundMessage

from .test_s17_integration import MockHospital, approve_referral, run_delivery

PATIENT = "pat_ravi"


@pytest.fixture()
def mock(monkeypatch):
    server = MockHospital()
    monkeypatch.setenv("FHIR_BASE_URL", server.base)
    monkeypatch.delenv("FHIR_AUTH_TOKEN", raising=False)
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def unconfigured(monkeypatch):
    monkeypatch.delenv("FHIR_BASE_URL", raising=False)


def _approve_new(client) -> str:
    known = {r["id"] for r in client.get("/api/referrals").json()["referrals"]}
    approve_referral(client)
    new = [r for r in client.get("/api/referrals").json()["referrals"] if r["id"] not in known]
    assert len(new) == 1
    return new[0]["id"]


def _row(referral_id: str) -> Referral:
    db = SessionLocal()
    try:
        row = db.get(Referral, referral_id)
        db.expunge(row)
        return row
    finally:
        db.close()


def _message() -> OutboundMessage:
    db = SessionLocal()
    try:
        row = db.scalars(select(OutboundMessage).order_by(OutboundMessage.created_at.desc())).first()
        db.expunge(row)
        return row
    finally:
        db.close()


def test_without_an_integration_the_referral_is_queued_not_sent(client, unconfigured):
    referral_id = _approve_new(client)
    shown = next(r for r in client.get("/api/referrals").json()["referrals"] if r["id"] == referral_id)
    assert shown["status"] == "queued"
    assert shown["sent_at"] is None
    assert _message().status == "not_configured"
    status = client.get("/api/integrations/status").json()
    assert status["configured"] is False and status["not_configured"] == 1
    assert "not sent" in status["banner"]
    assert run_delivery()["sent"] == 0
    assert _row(referral_id).status == "queued" and _row(referral_id).sent_at is None


def test_without_an_integration_acknowledge_and_complete_still_work_and_never_say_sent(client, unconfigured):
    referral_id = _approve_new(client)
    ack = client.post(f"/api/referrals/{referral_id}/acknowledge", json={})
    assert ack.status_code == 200 and ack.json()["status"] == "acknowledged"
    done = client.post(f"/api/referrals/{referral_id}/complete", json={"response_summary": "Seen."})
    assert done.status_code == 200 and done.json()["status"] == "completed"
    assert done.json()["sent_at"] is None
    types = {e["type"] for e in client.get(f"/api/patients/{PATIENT}/timeline").json()["events"]
             if e["payload"].get("referral_id") == referral_id}
    assert {"referral", "referral_update", "referral_consult"} <= types


def test_a_queued_referral_can_be_completed_directly(client, unconfigured):
    referral_id = _approve_new(client)
    done = client.post(f"/api/referrals/{referral_id}/complete", json={"response_summary": "Phoned back."})
    assert done.status_code == 200 and done.json()["status"] == "completed"


def test_a_2xx_delivery_marks_the_referral_sent_with_the_real_time(client, mock):
    referral_id = _approve_new(client)
    assert (_row(referral_id).status, _row(referral_id).sent_at) == ("queued", None)
    assert mock.posts == []
    assert run_delivery()["sent"] == 1
    assert len(mock.posts) == 1
    row, message = _row(referral_id), _message()
    assert row.status == "sent"
    assert row.sent_at is not None and row.sent_at == message.sent_at
    shown = next(r for r in client.get("/api/referrals").json()["referrals"] if r["id"] == referral_id)
    assert shown["status"] == "sent" and shown["sent_at"] == message.sent_at.isoformat()
    assert client.post(f"/api/referrals/{referral_id}/acknowledge", json={}).json()["status"] == "acknowledged"


def test_a_500_leaves_the_referral_queued_until_a_later_run_succeeds(client, mock):
    referral_id = _approve_new(client)
    mock.post_status = 500
    start = utcnow()
    assert run_delivery(now=start) == {"sent": 0, "requeued": 1, "failed": 0, "not_configured": 0}
    assert (_row(referral_id).status, _row(referral_id).sent_at) == ("queued", None)
    assert _message().attempts == 1
    mock.post_status = 201
    assert run_delivery(now=start + timedelta(seconds=600))["sent"] == 1
    row = _row(referral_id)
    assert row.status == "sent" and row.sent_at == _message().sent_at


def test_a_message_held_for_no_address_goes_out_and_marks_the_referral_once_an_address_is_set(client, mock, monkeypatch):
    monkeypatch.delenv("FHIR_BASE_URL")
    referral_id = _approve_new(client)
    assert _message().status == "not_configured" and _row(referral_id).status == "queued"
    monkeypatch.setenv("FHIR_BASE_URL", mock.base)
    assert run_delivery()["sent"] == 1
    assert _row(referral_id).status == "sent" and _row(referral_id).sent_at is not None


def test_delivery_after_staff_acknowledged_keeps_the_status_but_records_the_send_time(client, mock):
    referral_id = _approve_new(client)
    assert client.post(f"/api/referrals/{referral_id}/acknowledge", json={}).status_code == 200
    assert run_delivery()["sent"] == 1
    row = _row(referral_id)
    assert row.status == "acknowledged" and row.sent_at == _message().sent_at


def test_a_permanent_rejection_leaves_the_referral_queued_and_unsent(client, mock):
    referral_id = _approve_new(client)
    mock.post_status = 400
    assert run_delivery()["failed"] == 1
    assert _message().status == "failed"
    assert (_row(referral_id).status, _row(referral_id).sent_at) == ("queued", None)
