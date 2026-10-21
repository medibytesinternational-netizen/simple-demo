"""Rule 5: the hospital keeps its HMS and EMR; MediBytes connects by API (FHIR R4).

A stdlib mock FHIR server (127.0.0.1, OS-assigned port, own thread) stands in for the hospital
system. Inbound: bundles through POST /api/ingest/fhir and the pull command. Outbound: approved
orders reach the mock as ServiceRequests, with honest status when the link is down or unset.
"""

from __future__ import annotations

import json
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

import app.background as background
from app.db import SessionLocal, utcnow
from app.integrations import outbox, pull
from app.integrations.fhir import bundle_to_events
from app.models import Alert, Encounter, Patient, TimelineEvent
from app.models_ext.s17_integration import IntegrationSync, OutboundMessage
from app.services.timeline import get_state

HMS = {"X-User-Id": "u_hms"}
SYSTEM = "demo-hms"
MR = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "MR"}]}


# ---------------------------------------------------------------- mock hospital system
class MockHospital(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.base = f"http://127.0.0.1:{self.server_address[1]}"
        self.posts: list[dict] = []
        self.gets: list[str] = []
        self.post_status = 201
        self.mrn = "MB-1001"
        self.observation_pages: list[list[dict]] = [[], []]
        self.medications: list[dict] = []
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=5)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status: int, body: dict | None = None, headers: dict | None = None):
        raw = json.dumps(body or {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(raw)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        server: MockHospital = self.server  # type: ignore[assignment]
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        server.posts.append({"path": self.path, "body": body, "headers": dict(self.headers)})
        status = server.post_status
        self._send(status, {"resourceType": "ServiceRequest", "id": "hms-1"},
                   {"Location": server.base + "/elsewhere"} if 300 <= status < 400 else None)

    def do_GET(self):
        server: MockHospital = self.server  # type: ignore[assignment]
        server.gets.append(self.path)
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        if parts.path == "/Patient":
            if query.get("identifier") == [server.mrn]:
                self._send(200, {"resourceType": "Bundle", "entry": [{"resource": patient_resource(server.mrn)}]})
            else:
                self._send(200, {"resourceType": "Bundle", "entry": []})
        elif parts.path == "/Observation":
            page = int(query.get("page", ["1"])[0])
            body = {"resourceType": "Bundle", "entry": [{"resource": r} for r in server.observation_pages[page - 1]]}
            if page < len(server.observation_pages):
                body["link"] = [{"relation": "next", "url": f"{server.base}/Observation?patient=hp1&page={page + 1}"}]
            self._send(200, body)
        elif parts.path == "/MedicationRequest":
            self._send(200, {"resourceType": "Bundle", "entry": [{"resource": r} for r in server.medications]})
        else:
            self._send(404, {"resourceType": "OperationOutcome"})


@pytest.fixture()
def mock(monkeypatch):
    server = MockHospital()
    monkeypatch.setenv("FHIR_BASE_URL", server.base)
    monkeypatch.delenv("FHIR_AUTH_TOKEN", raising=False)
    try:
        yield server
    finally:
        server.stop()


# ---------------------------------------------------------------- FHIR builders
def patient_resource(mrn: str = "MB-1001", pid: str = "hp1") -> dict:
    return {"resourceType": "Patient", "id": pid, "identifier": [{"type": MR, "value": mrn}]}


def lab(rid, name, value, unit, flag=None, low=None, high=None, text=None, version="1", when="2026-10-20T10:00:00Z"):
    resource = {
        "resourceType": "Observation", "id": rid, "meta": {"versionId": version}, "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory"}]}],
        "code": {"text": name}, "subject": {"reference": "Patient/hp1"},
        "effectiveDateTime": when, "valueQuantity": {"value": value, "unit": unit},
    }
    if flag:
        resource["interpretation"] = [{"coding": [{"code": flag}]}]
    range_ = {}
    if low is not None:
        range_["low"] = {"value": low}
    if high is not None:
        range_["high"] = {"value": high}
    if text:
        range_["text"] = text
    if range_:
        resource["referenceRange"] = [range_]
    return resource


def vital(rid, name, components=None, value=None, unit=""):
    resource = {
        "resourceType": "Observation", "id": rid, "status": "final",
        "category": [{"coding": [{"code": "vital-signs"}]}], "code": {"text": name},
        "subject": {"reference": "Patient/hp1"}, "effectiveDateTime": "2026-10-20T10:05:00Z",
    }
    if components:
        resource["component"] = [{"code": {"text": n}, "valueQuantity": {"value": v, "unit": "mmHg"}} for n, v in components]
    else:
        resource["valueQuantity"] = {"value": value, "unit": unit}
    return resource


def medication(rid, drug, status="active", version="1", intent="order", dose=500, frequency=2):
    return {
        "resourceType": "MedicationRequest", "id": rid, "meta": {"versionId": version}, "status": status,
        "intent": intent, "medicationCodeableConcept": {"text": drug}, "subject": {"reference": "Patient/hp1"},
        "authoredOn": "2026-10-20T09:30:00Z", "reasonCode": [{"text": "Infection"}],
        "dosageInstruction": [{
            "route": {"text": "Oral"},
            "timing": {"repeat": {"frequency": frequency, "period": 1, "periodUnit": "d"}},
            "doseAndRate": [{"doseQuantity": {"value": dose, "unit": "mg"}}],
        }],
    }


def bundle(*resources, patient=True, mrn="MB-1001") -> dict:
    entries = ([{"resource": patient_resource(mrn)}] if patient else []) + [{"resource": r} for r in resources]
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}


def ingest(client, *resources, headers=HMS, **kwargs):
    return client.post("/api/ingest/fhir", json={"system": SYSTEM, "bundle": bundle(*resources, **kwargs)}, headers=headers)


def fhir_events(patient_id="pat_ravi") -> list[TimelineEvent]:
    db = SessionLocal()
    try:
        return list(db.scalars(select(TimelineEvent).where(
            TimelineEvent.patient_id == patient_id, TimelineEvent.source == f"fhir:{SYSTEM}"
        ).order_by(TimelineEvent.created_at)))
    finally:
        db.close()


def messages() -> list[OutboundMessage]:
    db = SessionLocal()
    try:
        return list(db.scalars(select(OutboundMessage).order_by(OutboundMessage.created_at)))
    finally:
        db.close()


def run_delivery(now=None, transport=None) -> dict:
    db = SessionLocal()
    try:
        result = outbox.deliver(db, transport=transport, now=now)
        db.commit()
        return result
    finally:
        db.close()


def approve_referral(client) -> dict:
    draft = client.post("/api/referrals/generate", json={
        "specialty": "Nephrology",
        "question": "Please advise on whether the falling kidney function needs a change of medicines.",
    }).json()["draft"]
    response = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert response.status_code == 200, response.text
    return draft


def approve_investigation(client) -> dict:
    draft = client.post("/api/investigation-requests/generate", json={}).json()["draft"]
    for item in draft["content"]["allergies_to_verify"]:
        assert client.post(f"/api/drafts/{draft['id']}/verify-allergy", json={"substance": item["substance"]}).status_code == 200
    response = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert response.status_code == 200, response.text
    return draft


# ================================================================ inbound
def test_bundle_creates_events_once_and_a_resend_is_skipped(client):
    resources = [lab("o1", "Potassium", 5.9, "mmol/L", "HH"), medication("m1", "Metformin")]
    first = ingest(client, *resources)
    assert first.status_code == 200, first.text
    body = first.json()
    assert (body["created"], body["skipped"], body["errors"]) == (2, 0, 0)
    events = fhir_events()
    assert sorted(e.type for e in events) == ["lab_result", "med_order"]
    assert {e.source for e in events} == {f"fhir:{SYSTEM}"}
    assert {e.payload["external_id"] for e in events} == {f"{SYSTEM}:Observation/o1", f"{SYSTEM}:MedicationRequest/m1"}
    again = ingest(client, *resources).json()
    assert (again["created"], again["skipped"], again["errors"]) == (0, 2, 0)
    assert len(fhir_events()) == 2


def test_a_higher_version_supersedes_the_earlier_event(client):
    ingest(client, lab("o1", "Potassium", 5.9, "mmol/L", "HH", version="1"))
    second = ingest(client, lab("o1", "Potassium", 4.1, "mmol/L", "N", version="2")).json()
    assert second["created"] == 1
    old, new = sorted(fhir_events(), key=lambda e: e.payload["external_version"])
    assert old.status == "superseded"
    assert new.status == "approved" and new.supersedes_event_id == old.id
    assert new.payload["value"] == 4.1
    db = SessionLocal()
    try:
        state = get_state(db, db.get(Patient, "pat_ravi"), db.get(Encounter, "enc_ipd_1"))
        potassium = [lab_ for lab_ in state["latest_labs"] if lab_["name"] == "Potassium"]
        assert [lab_["value"] for lab_ in potassium] == [4.1]
    finally:
        db.close()
    stale = ingest(client, lab("o1", "Potassium", 9.9, "mmol/L", "HH", version="1")).json()
    assert (stale["created"], stale["skipped"]) == (0, 1)


def test_unknown_resource_types_are_skipped_and_counted(client):
    result = ingest(client, {"resourceType": "Procedure", "id": "p1"}, {"resourceType": "Encounter", "id": "e1"},
                    lab("o1", "Potassium", 4.0, "mmol/L")).json()
    assert (result["created"], result["skipped"], result["errors"]) == (1, 2, 0)
    reasons = [d["reason"] for d in result["details"] if d["outcome"] == "skipped"]
    assert sorted(reasons) == ["unsupported resource type Encounter", "unsupported resource type Procedure"]


def test_units_reference_ranges_and_flags_map():
    flags = {}
    for code in ["H", "L", "N", "HH", "LL"]:
        item = bundle_to_events(bundle(lab("o", "X", 1, "u", code)), SYSTEM)["items"][0]
        flags[code] = item["payload"]["flag"]
    assert flags == {"H": "high", "L": "low", "N": "normal", "HH": "critical", "LL": "critical"}
    mapped = bundle_to_events(bundle(
        lab("a", "Creatinine", 2.9, "mg/dL", "H", low=0.7, high=1.3),
        lab("b", "eGFR", 22, "mL/min/1.73m²", "L", text="> 90"),
        lab("c", "Plain", 1, "g/L"),
    ), SYSTEM)["items"]
    by_name = {i["payload"]["name"]: i["payload"] for i in mapped}
    assert by_name["Creatinine"]["unit"] == "mg/dL" and by_name["Creatinine"]["reference_range"] == "0.7 - 1.3"
    assert by_name["eGFR"]["reference_range"] == "> 90" and by_name["eGFR"]["unit"] == "mL/min/1.73m²"
    assert by_name["Creatinine"]["review_status"] == "unreviewed"
    assert by_name["Creatinine"]["collected_at"] == "2026-10-20T10:00:00"
    assert by_name["Plain"]["flag"] == "unknown", "a flag the source did not send is not invented"
    reading = bundle_to_events(bundle(vital("v1", "Blood pressure", components=[("Systolic", 132), ("Diastolic", 84)])), SYSTEM)["items"][0]
    assert reading["type"] == "device_reading"
    assert reading["payload"]["category"] == "vitals" and reading["payload"]["value"] == "132/84"
    assert reading["payload"]["unit"] == "mmHg"


def test_only_the_integration_user_may_ingest(client):
    for user in ["u_meera", "u_anita", "u_dev", "u_billing", "u_mgmt"]:
        response = ingest(client, lab("o1", "Potassium", 4.0, "mmol/L"), headers={"X-User-Id": user})
        assert response.status_code == 403, user
    assert fhir_events() == []
    assert ingest(client, lab("o1", "Potassium", 4.0, "mmol/L")).status_code == 200
    assert len(fhir_events()) == 1
    assert client.post("/api/ingest/fhir", json={"system": SYSTEM, "bundle": {"resourceType": "Patient"}}, headers=HMS).status_code == 400


def test_the_patient_is_matched_by_mrn_and_an_unknown_mrn_is_an_error(client):
    db = SessionLocal()
    try:
        other = db.scalar(select(Patient).where(Patient.mrn == "MB-2042"))
        other_id = other.id
    finally:
        db.close()
    result = client.post("/api/ingest/fhir", json={"system": SYSTEM, "bundle": bundle(
        lab("o1", "Potassium", 4.0, "mmol/L"), mrn="MB-2042")}, headers=HMS).json()
    assert result["created"] == 1
    assert [e.payload["external_id"] for e in fhir_events(other_id)] == [f"{SYSTEM}:Observation/o1"]
    assert fhir_events("pat_ravi") == []
    missing = client.post("/api/ingest/fhir", json={"system": SYSTEM, "bundle": bundle(
        lab("o2", "Potassium", 4.0, "mmol/L"), mrn="MB-NOPE")}, headers=HMS).json()
    assert (missing["created"], missing["errors"]) == (0, 1)
    assert "MB-NOPE" in missing["details"][0]["reason"]
    assert len(fhir_events(other_id)) == 1


def test_ingested_active_penicillin_order_raises_an_r2_alert_citing_the_ingested_event(fresh):
    result = ingest(fresh, medication("m1", "Amoxicillin")).json()
    assert result["created"] == 1 and len(result["alerts_created"]) >= 1
    event = fhir_events()[0]
    alerts = fresh.get("/api/alerts").json()["alerts"]
    r2 = [a for a in alerts if a["rule_id"] == "R2" and a["status"] == "open"]
    assert len(r2) == 1
    assert event.id in r2[0]["evidence_event_ids"]
    assert event.payload["kind"] == "inpatient" and event.payload["status"] == "active"
    assert (event.payload["dose"], event.payload["route"], event.payload["indication"]) == ("500 mg", "Oral", "Infection")
    assert event.payload["frequency"] == "2 per day"


def test_a_stopped_version_removes_the_drug_from_the_active_medicines(fresh):
    for status, version in [("active", "1"), ("completed", "2")]:
        ingest(fresh, medication("m1", "Amoxicillin", status=status, version=version))
    db = SessionLocal()
    try:
        state = get_state(db, db.get(Patient, "pat_ravi"), db.get(Encounter, "enc_ipd_1"))
        assert "amoxicillin" not in [m["drug"].lower() for m in state["active_meds"]]
    finally:
        db.close()
    assert sorted(e.payload["status"] for e in fhir_events()) == ["active", "stopped"]


def test_drafts_and_proposals_are_not_orders(client):
    result = ingest(client, medication("m1", "Warfarin", status="draft"),
                    medication("m2", "Warfarin", intent="proposal"),
                    medication("m3", "Warfarin", status="cancelled")).json()
    assert (result["created"], result["skipped"]) == (1, 2)
    assert [e.payload["status"] for e in fhir_events()] == ["stopped"]


def test_allergy_and_problem_update_the_patient_without_duplicates(client):
    allergy = {"resourceType": "AllergyIntolerance", "id": "a1", "code": {"text": "Latex"},
               "subject": {"reference": "Patient/hp1"},
               "reaction": [{"manifestation": [{"text": "hives"}]}]}
    seeded = {"resourceType": "AllergyIntolerance", "id": "a2", "code": {"text": "penicillin"},
              "subject": {"reference": "Patient/hp1"}, "reaction": [{"manifestation": [{"text": "rash"}]}]}
    condition = {"resourceType": "Condition", "id": "c1", "code": {"text": "Gout"},
                 "subject": {"reference": "Patient/hp1"}}
    listed = {"resourceType": "Condition", "id": "c2", "code": {"text": "hypertension"},
              "subject": {"reference": "Patient/hp1"}}
    first = ingest(client, allergy, seeded, condition, listed).json()
    assert (first["created"], first["skipped"]) == (3, 1), "an already-listed problem is not added again"
    db = SessionLocal()
    try:
        patient = db.get(Patient, "pat_ravi")
        assert patient.allergies.count("Latex — hives") == 1
        assert [a for a in patient.allergies if a.lower().startswith("penicillin")] == ["Penicillin — rash"]
        assert patient.problems.count("Gout") == 1
        assert [p for p in patient.problems if p.lower() == "hypertension"] == ["Hypertension"]
    finally:
        db.close()
    assert sorted(e.type for e in fhir_events()) == ["allergy_record", "allergy_record"]
    again = ingest(client, allergy, seeded, condition, listed).json()
    assert (again["created"], again["skipped"]) == (0, 4)
    db = SessionLocal()
    try:
        assert db.get(Patient, "pat_ravi").problems.count("Gout") == 1
    finally:
        db.close()


def test_ingest_records_a_sync_row_and_the_status_endpoint_reports_it(client, monkeypatch):
    monkeypatch.delenv("FHIR_BASE_URL", raising=False)
    assert client.get("/api/integrations/status").json()["last_sync_at"] is None
    ingest(client, lab("o1", "Potassium", 4.0, "mmol/L"), {"resourceType": "Procedure", "id": "p"})
    db = SessionLocal()
    try:
        rows = list(db.scalars(select(IntegrationSync)))
        assert [(r.system, r.status, r.created, r.skipped, r.errors) for r in rows] == [(SYSTEM, "ok", 1, 1, 0)]
        stamp = rows[0].finished_at
    finally:
        db.close()
    status = client.get("/api/integrations/status").json()
    assert status["last_sync_status"] == "ok"
    assert status["last_sync_at"] == stamp.isoformat()
    assert f"Last synced {stamp:%H:%M}." in status["banner"]


# ================================================================ outbound
def test_approving_a_referral_queues_a_service_request_that_a_delivery_run_sends(client, mock):
    approve_referral(client)
    queued = messages()
    assert [(m.resource_type, m.status, m.attempts) for m in queued] == [("ServiceRequest", "queued", 0)]
    assert mock.posts == [], "approval itself never calls the hospital system"
    assert run_delivery() == {"sent": 1, "requeued": 0, "failed": 0, "not_configured": 0}
    assert [p["path"] for p in mock.posts] == ["/ServiceRequest"]
    request = mock.posts[0]["body"]
    assert request["resourceType"] == "ServiceRequest" and request["intent"] == "order"
    assert request["category"][0]["text"] == "referral"
    assert request["code"]["text"] == "Nephrology"
    assert "falling kidney function" in request["note"][0]["text"]
    assert request["subject"]["identifier"]["value"] == "MB-1001"
    assert mock.posts[0]["headers"]["Content-Type"] == "application/fhir+json"
    sent = messages()[0]
    assert sent.status == "sent" and sent.attempts == 1 and sent.sent_at is not None
    assert sent.source_event_id and sent.patient_id == "pat_ravi"
    assert run_delivery()["sent"] == 0 and len(mock.posts) == 1, "a sent message is never sent twice"


def test_approving_an_investigation_form_queues_a_service_request(client, mock):
    draft = approve_investigation(client)
    assert [m.status for m in messages()] == ["queued"]
    run_delivery()
    request = mock.posts[0]["body"]
    assert request["category"][0]["text"] in {"laboratory", "imaging"}
    assert request["code"]["text"] == draft["content"]["study"]
    assert request["reasonCode"][0]["text"] == draft["content"]["indication"]["text"]
    allergy_note = [n["text"] for n in request["note"] if n["text"].startswith("Allergies to verify")]
    assert allergy_note and "Penicillin" in allergy_note[0]


def test_a_failing_hospital_system_keeps_the_message_queued_and_a_later_run_sends_it(client, mock):
    approve_referral(client)
    mock.post_status = 500
    start = utcnow()
    assert run_delivery(now=start)["requeued"] == 1
    message = messages()[0]
    assert (message.status, message.attempts, message.last_error) == ("queued", 1, "HTTP 500")
    assert message.sent_at is None
    assert message.next_attempt_at == start + timedelta(seconds=30)
    assert run_delivery(now=start + timedelta(seconds=10)) == {"sent": 0, "requeued": 0, "failed": 0, "not_configured": 0}
    assert len(mock.posts) == 1, "not retried before next_attempt_at"
    assert run_delivery(now=start + timedelta(seconds=31))["requeued"] == 1
    second = messages()[0]
    assert second.attempts == 2
    assert second.next_attempt_at == start + timedelta(seconds=31 + 60)
    mock.post_status = 201
    assert run_delivery(now=start + timedelta(seconds=200))["sent"] == 1
    done = messages()[0]
    assert (done.status, done.attempts) == ("sent", 3)
    assert len(mock.posts) == 3


def test_backoff_doubles_from_thirty_seconds_to_one_hour():
    assert [outbox.backoff_seconds(n) for n in range(1, 10)] == [30, 60, 120, 240, 480, 960, 1920, 3600, 3600]


def test_no_message_is_sent_without_a_2xx(client, mock):
    approve_referral(client)
    now = utcnow()
    mock.post_status = 302
    assert run_delivery(now=now)["requeued"] == 1
    assert messages()[0].status == "queued" and len(mock.posts) == 1, "a redirect is not followed or trusted"
    mock.post_status = 404
    assert run_delivery(now=now + timedelta(seconds=40))["failed"] == 1
    failed = messages()[0]
    assert (failed.status, failed.sent_at, failed.last_error) == ("failed", None, "HTTP 404")
    status = client.get("/api/integrations/status").json()
    assert (status["failed"], status["queued"]) == (1, 0)
    assert "1 message failed to send." in status["banner"]


def test_a_dropped_connection_is_a_retry_not_a_send(client, mock):
    approve_referral(client)

    def broken(url, body, headers, timeout):
        raise ConnectionResetError("link down")

    assert run_delivery(transport=broken)["requeued"] == 1
    message = messages()[0]
    assert (message.status, message.attempts, message.last_error) == ("queued", 1, "network error: ConnectionResetError")
    assert mock.posts == []


def test_without_a_base_url_the_message_is_not_configured_and_status_says_so(client, monkeypatch):
    monkeypatch.delenv("FHIR_BASE_URL", raising=False)
    approve_referral(client)
    assert [m.status for m in messages()] == ["not_configured"]
    assert run_delivery() == {"sent": 0, "requeued": 0, "failed": 0, "not_configured": 0}
    assert messages()[0].status == "not_configured" and messages()[0].attempts == 0
    status = client.get("/api/integrations/status").json()
    assert (status["configured"], status["host"], status["not_configured"], status["queued"]) == (False, "", 1, 0)
    assert status["banner"] == "No hospital system is connected. 1 message held, not sent."


def test_a_held_message_is_sent_once_an_address_is_set(client, mock, monkeypatch):
    monkeypatch.delenv("FHIR_BASE_URL", raising=False)
    approve_referral(client)
    assert messages()[0].status == "not_configured"
    monkeypatch.setenv("FHIR_BASE_URL", mock.base)
    assert run_delivery()["sent"] == 1
    assert messages()[0].status == "sent" and len(mock.posts) == 1


def test_status_shows_the_host_only_and_never_credentials(client, mock, monkeypatch):
    monkeypatch.setenv("FHIR_BASE_URL", f"http://nurse:s3cret@127.0.0.1:{mock.server_address[1]}/fhir?token=abc")
    monkeypatch.setenv("FHIR_AUTH_TOKEN", "tok-123")
    approve_referral(client)
    body = client.get("/api/integrations/status", headers={"X-User-Id": "u_mgmt"}).json()
    assert body["configured"] is True
    assert body["host"] == f"127.0.0.1:{mock.server_address[1]}"
    text = json.dumps(body)
    for secret in ("s3cret", "nurse", "abc", "tok-123"):
        assert secret not in text
    assert body["banner"] == "Nothing received from the hospital system yet. 1 message waiting."


def test_credentials_in_the_address_are_sent_as_headers_not_in_the_url(client, mock, monkeypatch):
    monkeypatch.setenv("FHIR_BASE_URL", f"http://nurse:s3cret@127.0.0.1:{mock.server_address[1]}")
    approve_referral(client)
    assert run_delivery()["sent"] == 1
    assert mock.posts[0]["headers"]["Authorization"].startswith("Basic ")
    assert mock.posts[0]["path"] == "/ServiceRequest"
    monkeypatch.setenv("FHIR_AUTH_TOKEN", "tok-123")
    approve_referral(client)
    run_delivery()
    assert mock.posts[1]["headers"]["Authorization"] == "Bearer tok-123"


def test_only_the_integration_user_retries_and_retry_requeues_failed_messages(client, mock):
    approve_referral(client)
    mock.post_status = 400
    run_delivery()
    assert messages()[0].status == "failed"
    assert client.post("/api/integrations/outbox/retry").status_code == 403
    assert client.post("/api/integrations/outbox/retry", headers=HMS).json() == {"requeued": 1}
    again = messages()[0]
    assert (again.status, again.attempts) == ("queued", 0)
    mock.post_status = 201
    assert run_delivery()["sent"] == 1


def test_delivery_is_registered_as_a_background_job(client, mock):
    job = background.JOBS["outbox-delivery"]
    assert job.interval_seconds == 60
    approve_referral(client)
    assert background.run_job("outbox-delivery") == {"sent": 1, "requeued": 0, "failed": 0, "not_configured": 0}
    assert messages()[0].status == "sent"


# ================================================================ pull
def test_the_pull_command_reaches_the_mock_and_ingests_through_the_same_mappers(client, mock, capsys):
    mock.observation_pages = [
        [lab("o1", "Potassium", 5.9, "mmol/L", "HH", low=3.5, high=5.1)],
        [vital("v1", "Heart rate", value=88, unit="/min")],
    ]
    mock.medications = [medication("m1", "Metformin")]
    code = pull.main(["--base-url", mock.base, "--mrn", "MB-1001", "--system", SYSTEM])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["created"], out["skipped"], out["errors"]) == (3, 0, 0)
    assert any(path.startswith("/Observation") and "page=2" in path for path in mock.gets), "next page followed"
    events = {e.payload["external_id"]: e for e in fhir_events()}
    assert set(events) == {f"{SYSTEM}:Observation/o1", f"{SYSTEM}:Observation/v1", f"{SYSTEM}:MedicationRequest/m1"}
    assert events[f"{SYSTEM}:Observation/o1"].payload["reference_range"] == "3.5 - 5.1"
    assert events[f"{SYSTEM}:Observation/v1"].type == "device_reading"
    # The same data posted as a bundle is now a duplicate: one set of mappers, one set of ids.
    posted = ingest(client, lab("o1", "Potassium", 5.9, "mmol/L", "HH"), medication("m1", "Metformin")).json()
    assert (posted["created"], posted["skipped"]) == (0, 2)
    db = SessionLocal()
    try:
        kinds = [r.kind for r in db.scalars(select(IntegrationSync).order_by(IntegrationSync.started_at))]
    finally:
        db.close()
    assert kinds == ["pull", "inbound"]


def test_the_pull_command_reports_an_unknown_patient_and_a_dead_server(client, mock, capsys):
    mock.mrn = "MB-OTHER"
    assert pull.main(["--base-url", mock.base, "--mrn", "MB-1001", "--system", SYSTEM]) == 1
    assert json.loads(capsys.readouterr().out)["errors"] == 1
    assert fhir_events() == []
    status = client.get("/api/integrations/status").json()
    assert status["last_sync_status"] == "failed"
    assert "Last sync failed at" in status["banner"]
    dead = mock.base
    mock.stop()
    assert pull.main(["--base-url", dead, "--mrn", "MB-1001", "--system", SYSTEM]) == 1
    assert json.loads(capsys.readouterr().out)["errors"] == 1


def test_a_next_page_link_to_another_server_is_not_followed(client, mock):
    def fetch(url):
        if url.endswith("/Patient?identifier=MB-1001"):
            return {"entry": [{"resource": patient_resource()}]}
        return {"entry": [], "link": [{"relation": "next", "url": "http://evil.example/Observation"}]}

    db = SessionLocal()
    try:
        result = pull.pull(db, mock.base, "MB-1001", SYSTEM, fetch=fetch)
        db.commit()
    finally:
        db.close()
    assert result["errors"] == 1 and "different server" in result["details"][0]["reason"]
