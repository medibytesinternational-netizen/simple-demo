"""A doctor's progress note that asks for a scan or report raises an investigation request."""

from __future__ import annotations

from app.services.investigation_mentions import find_orders

from .helpers import FakeMediBytesHTTP
from .test_progress_notes import _record


def _auto(client):
    rows = client.get("/api/investigation-requests").json()["requests"]
    return [r for r in rows if r["status"] == "requested"]


def test_orders_are_found_and_results_are_not():
    assert [o["study"] for o in find_orders(["Plan: get CT abdomen and repeat CBC."])] == ["CT abdomen", "Complete blood count"]
    assert find_orders(["CT abdomen was normal."]) == []
    assert find_orders(["No need for MRI."]) == []
    assert find_orders(["The patient is conscious and oriented."]) == []
    assert find_orders(["Send blood culture urgently."])[0]["priority"] == "urgent"


def test_a_doctor_note_raises_marked_requests(client, monkeypatch):
    fake = FakeMediBytesHTTP().install(monkeypatch)
    entry = _record(client, fake, texts=("Leg swelling better", "Get CT abdomen and repeat CBC tomorrow"))
    raised = _auto(client)
    assert {(r["study"], r["request_type"]) for r in raised} == {("CT abdomen", "imaging"), ("Complete blood count", "laboratory")}
    assert all(r["source_event_id"] == entry["event_id"] for r in raised)
    events = client.get("/api/patients/pat_ravi/timeline?limit=200").json()["events"]
    note = next(e for e in events if e["id"] == entry["event_id"])
    assert [o["study"] for o in note["payload"]["orders"]] == ["CT abdomen", "Complete blood count"]
    assert all(o["sentence_index"] == 1 for o in note["payload"]["orders"])


def test_the_same_study_is_not_raised_twice(client, monkeypatch):
    fake = FakeMediBytesHTTP().install(monkeypatch)
    _record(client, fake, texts=("Get CT abdomen",))
    _record(client, fake, texts=("Get CT abdomen today",))
    assert [r["study"] for r in _auto(client)] == ["CT abdomen"]


def test_a_nurse_note_raises_nothing(client, monkeypatch):
    fake = FakeMediBytesHTTP().install(monkeypatch)
    _record(client, fake, headers={"X-User-Id": "u_anita"}, texts=("Doctor asked to get CT abdomen",))
    assert _auto(client) == []


def test_a_requested_investigation_can_be_sent(client, monkeypatch):
    fake = FakeMediBytesHTTP().install(monkeypatch)
    _record(client, fake, texts=("Advise chest x-ray",))
    request = _auto(client)[0]
    sent = client.post(f"/api/investigation-requests/{request['id']}/export")
    assert sent.status_code == 200 and sent.json()["status"] == "exported"


def test_a_plan_dictated_as_a_list_raises_requests():
    found = find_orders([
        "CT abdomen and pelvis with contrast to rule out an intraabdominal collection",
        "MRI lumbosacral spine to rule out a lumbar disc prolapse",
        "Patient is stable",
        "ECG done, normal.",
    ])
    assert [(o["study"], o["request_type"]) for o in found] == [
        ("CT abdomen and pelvis with contrast", "imaging"), ("MRI lumbosacral spine", "imaging")]
    assert [o["study"] for o in find_orders(["ECG to be done"])] == ["ECG"]
    assert [o["study"] for o in find_orders(["Repeat CT scan of the brain today"])] == ["CT brain"]


def test_rescan_raises_for_old_notes_once(client, monkeypatch):
    from app.db import SessionLocal
    from app.scripts.rescan_progress_orders import rescan

    fake = FakeMediBytesHTTP().install(monkeypatch)
    _record(client, fake, texts=("MRI lumbosacral spine to rule out a lumbar disc prolapse",))
    with SessionLocal() as db:
        rescan(db)
        rescan(db)
    assert [r["study"] for r in _auto(client)] == ["MRI lumbosacral spine"]
