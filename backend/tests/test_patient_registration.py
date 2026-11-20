"""New patient flow: register, record the consultation, upload old reports, all on the patient's own timeline.

The signed OPD note is stored as a document that the timeline can open and print.
"""

from __future__ import annotations

import pytest

from .helpers import ASTHMA, FakePipeline, text_pdf

NURSE = {"X-User-Id": "u_anita"}
LAB = ["CITY LAB REPORT", "Collected: 03 Sep 2026 07:40", "Creatinine 1.0 mg/dL (0.7-1.3)", "Potassium 4.1 mmol/L (3.5-5.1)"]
NEW = {"name": "Priya Nair", "age": 34, "sex": "Female", "allergies": ["Penicillin - rash"], "problems": ["Asthma"]}


def _register(client, body=None):
    response = client.post("/api/patients", json=body or NEW)
    assert response.status_code == 200, response.text
    return response.json()


def _as(pid):
    return {"X-Patient-Id": pid}


def _timeline(client, pid):
    return client.get(f"/api/patients/{pid}/timeline?limit=500", headers=_as(pid)).json()["events"]


def _sign_consult(client, pid):
    h = _as(pid)
    consent = client.post(f"/api/patients/{pid}/consents", json={"consent_type": "consultation_capture", "granted": True, "note": "t"}, headers=h)
    assert consent.status_code == 200, consent.text
    draft = client.post("/api/notes/generate", json={"feature": "F1", "transcript": ASTHMA}, headers=h)
    assert draft.status_code == 200, draft.text
    approved = client.post(f"/api/drafts/{draft.json()['draft']['id']}/approve", json={}, headers=h)
    assert approved.status_code == 200, approved.text
    return approved.json()["event"]


def test_registering_creates_patient_opd_visit_and_registration_event(client):
    body = _register(client)
    pid = body["patient"]["id"]
    assert body["patient"]["mrn"].startswith("MB-") and body["patient"]["mrn"] != "MB-1001"
    assert body["encounter"]["kind"] == "OPD" and body["encounter"]["status"] == "active"

    meta = client.get("/api/meta", headers=_as(pid)).json()
    assert meta["patient"]["id"] == pid
    events = _timeline(client, pid)
    assert [e["type"] for e in events] == ["registration"]
    assert events[0]["payload"]["allergies"] == ["Penicillin - rash"]
    assert pid in [p["id"] for p in client.get("/api/patients").json()["patients"]]


def test_mrns_are_unique_and_duplicates_and_missing_allergy_answers_are_refused(client):
    first = _register(client)["patient"]["mrn"]
    second = _register(client, {**NEW, "name": "Rahul Verma", "allergies": [], "no_known_allergies": True})["patient"]["mrn"]
    assert first != second
    assert client.post("/api/patients", json=NEW).status_code == 409
    assert client.post("/api/patients", json={**NEW, "name": "No Answer", "allergies": []}).status_code == 422


def test_a_role_without_register_patient_is_refused(client):
    assert client.post("/api/patients", json=NEW, headers=NURSE).status_code == 403


def test_signed_consult_lands_on_the_new_patient_only_with_a_stored_note_document(client):
    pid = _register(client)["patient"]["id"]
    ravi_before = len(_timeline(client, "pat_ravi"))
    event = _sign_consult(client, pid)

    notes = [e for e in _timeline(client, pid) if e["type"] == "consult_note"]
    assert [n["id"] for n in notes] == [event["id"]]
    assert len(_timeline(client, "pat_ravi")) == ravi_before

    doc_id = notes[0]["document_id"]
    assert doc_id
    stored = client.get(f"/api/documents/{doc_id}/file", headers=_as(pid))
    assert stored.status_code == 200
    assert "text/html" in stored.headers["content-type"]
    assert "Priya Nair" in stored.text and "OPD consultation note" in stored.text and "Signed by Dr. Meera Shah" in stored.text
    # The hospital OPD format, in its order, with the record headings filled from registration.
    order = ["Patient name", "Age and sex", "Date of admission", "Hospital number", "Department",
             "Unit and consultant", "History and physical recorded by", "Mode of admission", "Referring physician",
             "Previous admission", "Previous diagnosis", "Allergies (food, drugs, other)", "Pain (site, duration",
             "Occupation", "Source of history and reliability", "Chief complaints", "History of present illness"]
    positions = [stored.text.index(label) for label in order]
    assert positions == sorted(positions)
    assert "MB-1002" in stored.text or "MB-" in stored.text
    assert "Examination" not in stored.text and "Assessment" not in stored.text

    # The note is a record, not an inbound report to review.
    assert doc_id not in [d["id"] for d in client.get("/api/documents", headers=_as(pid)).json()["documents"]]
    assert doc_id in [d["id"] for d in client.get("/api/documents?include_generated=true", headers=_as(pid)).json()["documents"]]
    # Another patient cannot open it.
    assert client.get(f"/api/documents/{doc_id}/file").status_code == 404


def test_re_signing_keeps_the_earlier_note_document(client):
    pid = _register(client)["patient"]["id"]
    first = _sign_consult(client, pid)
    second = _sign_consult(client, pid)
    events = {e["id"]: e for e in _timeline(client, pid)}
    assert events[first["id"]]["status"] == "superseded"
    old_doc, new_doc = events[first["id"]]["document_id"], events[second["id"]]["document_id"]
    assert old_doc and new_doc and old_doc != new_doc
    assert client.get(f"/api/documents/{old_doc}/file", headers=_as(pid)).status_code == 200


def test_previous_report_upload_commits_under_the_new_patient(client):
    pid = _register(client)["patient"]["id"]
    response = client.post(
        "/api/documents/upload",
        files={"file": ("old-lab.pdf", text_pdf(LAB), "application/pdf")},
        data={"doc_type": "lab_report"},
        headers=_as(pid),
    )
    assert response.status_code == 200, response.text
    doc = response.json()
    labs = [e for e in _timeline(client, pid) if e["type"] == "lab_result"]
    assert {e["payload"]["document_id"] for e in labs} == {doc["id"]}
    assert len(labs) == 2
    assert not [e for e in _timeline(client, "pat_ravi") if e.get("payload", {}).get("document_id") == doc["id"]]


def test_drafts_are_listed_for_the_open_patient_only(client):
    pid = _register(client)["patient"]["id"]
    client.post(f"/api/patients/{pid}/consents", json={"consent_type": "consultation_capture", "granted": True, "note": "t"}, headers=_as(pid))
    draft = client.post("/api/notes/generate", json={"feature": "F1", "transcript": ASTHMA}, headers=_as(pid)).json()["draft"]
    mine = client.get("/api/drafts?feature=F1", headers=_as(pid)).json()["drafts"]
    ravis = client.get("/api/drafts?feature=F1").json()["drafts"]
    assert draft["id"] in [d["id"] for d in mine]
    assert draft["id"] not in [d["id"] for d in ravis]
    assert all(d["patient_id"] == pid for d in mine)


def test_an_unknown_patient_is_still_refused(client):
    assert client.get("/api/meta", headers=_as("pat_nobody")).status_code == 403


def test_the_cohort_is_gone_and_ravi_remains(client):
    ids = [p["id"] for p in client.get("/api/patients").json()["patients"]]
    assert ids == ["pat_ravi"]
    rows = client.get("/api/hospital/dashboard").json()["patients"]
    assert [r["patient_id"] for r in rows] == ["pat_ravi"]


def test_startup_removes_the_old_cohort_from_an_existing_database(client):
    from app.db import SessionLocal
    from app.models import Encounter, Patient, Task
    from app.seed import ensure_seed

    db = SessionLocal()
    try:
        db.add_all([
            Patient(id="pat_anita", mrn="MB-2042", name="Anita Desai", age=67, sex="Female"),
            Encounter(id="enc_ward_2", patient_id="pat_anita", kind="IPD", status="active"),
            Task(id="tsk_cohort_anita", patient_id="pat_anita", title="Old task"),
        ])
        db.commit()
        ensure_seed(db)
        assert db.get(Patient, "pat_anita") is None
        assert db.get(Encounter, "enc_ward_2") is None
        assert db.get(Task, "tsk_cohort_anita") is None
        assert db.get(Patient, "pat_ravi") is not None
    finally:
        db.close()
    assert [p["id"] for p in client.get("/api/patients").json()["patients"]] == ["pat_ravi"]


# ---------- intake: pre-fill from an old prescription or the consultation recording ----------

RX = [
    "CITY CLINIC - PRESCRIPTION",
    "Patient Name: Mrs. Lakshmi Iyer      Age/Sex: 52/F",
    "Mobile: +91 98400 12345",
    "Allergies: Sulfa drugs",
    "Diagnosis: Type 2 diabetes, Hypertension",
    "Tab Metformin 500 mg twice daily",
]


def _intake_doc(client, lines=RX, **headers):
    return client.post(
        "/api/intake/document",
        files={"file": ("old-rx.pdf", text_pdf(lines), "application/pdf")},
        data={"doc_type": "prescription"},
        headers=headers,
    )


def test_an_old_prescription_prefills_the_details(client):
    response = _intake_doc(client)
    assert response.status_code == 200, response.text
    body = response.json()
    f = {k: v["value"] for k, v in body["fields"].items()}
    assert body["status"] == "ready"
    assert f["name"] == "Lakshmi Iyer"
    assert f["age"] == 52 and f["sex"] == "Female"
    assert f["phone"].replace(" ", "") == "+919840012345"
    assert f["allergies"] == ["Sulfa drugs"]
    assert f["problems"] == ["Type 2 diabetes", "Hypertension"]
    assert all(v["source"] for v in body["fields"].values())  # each value shows where it was read


def test_registering_with_the_document_attaches_it_to_the_new_patient(client):
    intake_id = _intake_doc(client).json()["intake_id"]
    reg = client.post("/api/patients", json={
        "name": "Lakshmi Iyer", "age": 52, "sex": "Female", "allergies": ["Sulfa drugs"], "intake_ids": [intake_id],
    })
    assert reg.status_code == 200, reg.text
    pid = reg.json()["patient"]["id"]
    doc_id = reg.json()["attached"][0]["document_id"]
    docs = client.get("/api/documents", headers=_as(pid)).json()["documents"]
    assert [d["id"] for d in docs] == [doc_id]
    assert docs[0]["doc_type"] == "prescription"
    # Ravi does not get it, and the same intake cannot be attached twice.
    assert doc_id not in [d["id"] for d in client.get("/api/documents").json()["documents"]]
    again = client.post("/api/patients", json={**NEW, "name": "Someone Else", "intake_ids": [intake_id]})
    assert again.status_code == 409


def test_intake_needs_the_registration_permission_and_a_known_type(client):
    assert _intake_doc(client, **NURSE).status_code == 403
    bad = client.post("/api/intake/document", files={"file": ("x.pdf", text_pdf(RX), "application/pdf")}, data={"doc_type": "lab_report"})
    assert bad.status_code == 422


def test_the_document_type_is_worked_out_when_not_given(client):
    rx = client.post("/api/intake/document", files={"file": ("scan.pdf", text_pdf(RX), "application/pdf")}).json()
    assert rx["doc_type"] == "prescription"
    dc = client.post("/api/intake/document", files={"file": ("old.pdf", text_pdf([
        "DISCHARGE SUMMARY", "Name: Ramesh Kumar   Age: 61   Sex: Male", "Final diagnosis: Pneumonia",
    ]), "application/pdf")}).json()
    assert dc["doc_type"] == "discharge_summary"
    assert dc["fields"]["name"]["value"] == "Ramesh Kumar" and dc["fields"]["problems"]["value"] == ["Pneumonia"]
    assert client.post("/api/patients", json={**NEW, "intake_ids": ["itk_000000000000"]}).status_code == 404


@pytest.fixture()
def fake_pipeline(monkeypatch):
    fake = FakePipeline().install(monkeypatch)
    fake.transcript = (
        "Doctor: Good morning, what is your name? Patient: My name is Arjun Menon. "
        "I am 45 years old. I have diabetes. I am allergic to penicillin. "
        + fake.transcript
    )
    return fake


def test_the_recording_prefills_and_becomes_the_opd_draft_after_registration(client, fake_pipeline):
    refused = client.post("/api/intake/audio", files={"file": ("visit.webm", b"abc", "audio/webm")})
    assert refused.status_code == 403  # consent first
    sent = client.post("/api/intake/audio", files={"file": ("visit.webm", b"abc", "audio/webm")}, data={"consent": "true"})
    assert sent.status_code == 200, sent.text
    intake_id = sent.json()["intake_id"]
    # Registering before the recording is read is refused.
    assert client.post("/api/patients", json={**NEW, "intake_ids": [intake_id]}).status_code == 409

    status = client.get(f"/api/intake/{intake_id}").json()
    assert status["status"] == "ready"
    f = {k: v["value"] for k, v in status["fields"].items()}
    assert f["name"] == "Arjun Menon" and f["age"] == 45
    assert f["allergies"] == ["penicillin"] and f["problems"] == ["Diabetes"]

    reg = client.post("/api/patients", json={
        "name": "Arjun Menon", "age": 45, "sex": "Male", "allergies": ["penicillin"], "intake_ids": [intake_id],
    }).json()
    pid = reg["patient"]["id"]
    drafts = client.get("/api/drafts?feature=F1", headers=_as(pid)).json()["drafts"]
    assert [d["id"] for d in drafts] == [reg["attached"][0]["draft_id"]]
    assert drafts[0]["status"] == "draft_ready"  # still needs the doctor's review and signature
    types = {e["type"] for e in _timeline(client, pid)}
    assert {"registration", "consent"} <= types and "consult_note" not in types
    signed = client.post(f"/api/drafts/{drafts[0]['id']}/approve", json={}, headers=_as(pid))
    assert signed.status_code == 200, signed.text
    assert signed.json()["event"]["document_id"]


def test_a_signed_note_can_be_edited_and_resigned_which_updates_the_timeline(client):
    pid = _register(client)["patient"]["id"]
    h = _as(pid)
    first = _sign_consult(client, pid)
    draft_id = client.get("/api/drafts?feature=F1", headers=h).json()["drafts"][0]["id"]

    # A signed note cannot be patched directly; it is revised.
    assert client.patch(f"/api/drafts/{draft_id}", json={"content": {}}, headers=h).status_code >= 400
    revision = client.post(f"/api/drafts/{draft_id}/revise", headers=h)
    assert revision.status_code == 200, revision.text
    rev = revision.json()
    assert rev["id"] != draft_id and rev["status"] == "draft_ready"
    # Asking again returns the same open revision.
    assert client.post(f"/api/drafts/{draft_id}/revise", headers=h).json()["id"] == rev["id"]

    content = rev["content"]
    content["occupation"] = {"text": "Software engineer", "source_event_ids": [], "source_segment_ids": [],
                             "confidence": 1, "human_authored": True}
    edited = client.patch(f"/api/drafts/{rev['id']}", json={"content": content}, headers=h)
    assert edited.status_code == 200, edited.text
    signed = client.post(f"/api/drafts/{rev['id']}/approve", json={}, headers=h)
    assert signed.status_code == 200, signed.text
    new_event = signed.json()["event"]

    events = {e["id"]: e for e in _timeline(client, pid)}
    assert events[first["id"]]["status"] == "superseded"
    assert events[new_event["id"]]["payload"]["occupation"]["text"] == "Software engineer"
    # The document is formatted again from the edited note; the old one is kept.
    doc = client.get(f"/api/documents/{new_event['document_id']}/file", headers=h).text
    assert "Software engineer" in doc
    assert client.get(f"/api/documents/{first['document_id']}/file", headers=h).status_code == 200


def test_a_revision_is_the_latest_draft_even_after_the_clock_restarts(client):
    """The demo clock restarts with the server; Edit must still open the revision, not the signed note."""
    from datetime import timedelta

    from app.db import SessionLocal
    from app.models import Draft

    pid = _register(client)["patient"]["id"]
    h = _as(pid)
    _sign_consult(client, pid)
    signed = client.get("/api/drafts?feature=F1", headers=h).json()["drafts"][0]
    db = SessionLocal()
    try:  # as if the note was signed an hour "later" by a server that has since restarted
        db.get(Draft, signed["id"]).created_at += timedelta(hours=1)
        db.commit()
    finally:
        db.close()
    rev = client.post(f"/api/drafts/{signed['id']}/revise", headers=h).json()
    latest = client.get("/api/drafts?feature=F1&limit=1", headers=h).json()["drafts"][0]
    assert latest["id"] == rev["id"] and latest["status"] == "draft_ready"


def test_the_clock_carries_on_after_a_restart_instead_of_going_back():
    from datetime import timedelta

    from app import clock

    later = clock.now() + timedelta(hours=3)  # something recorded before a restart
    clock.resume_after(later)
    assert clock.now() >= later
    earlier = clock.now() - timedelta(days=1)
    before = clock.now()
    clock.resume_after(earlier)  # never moves back
    assert clock.now() >= before
    clock.reset()


def test_order_repair_fixes_restart_times_and_never_touches_seeded_history(client):
    from datetime import timedelta

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import TimelineEvent
    from app.seed import repair_event_order

    pid = _register(client)["patient"]["id"]
    _sign_consult(client, pid)
    db = SessionLocal()
    try:
        seeded = {e.id: (e.occurred_at, e.created_at) for e in db.scalars(select(TimelineEvent).where(TimelineEvent.patient_id == "pat_ravi"))}
        mine = list(db.scalars(select(TimelineEvent).where(TimelineEvent.patient_id == pid)))
        last = max(mine, key=lambda e: e.created_at)
        # As if the last entry was saved after a restart sent the clock back an hour.
        back = last.created_at - timedelta(hours=1)
        last.occurred_at = last.created_at = back
        db.commit()
        assert repair_event_order(db) >= 1
        db.refresh(last)
        others = [e for e in mine if e.id != last.id]
        assert all(last.created_at > e.created_at for e in others)
        assert last.occurred_at == last.created_at
        after = {e.id: (e.occurred_at, e.created_at) for e in db.scalars(select(TimelineEvent).where(TimelineEvent.patient_id == "pat_ravi"))}
        assert after == seeded
        assert repair_event_order(db) == 0
    finally:
        db.close()


def test_purge_keeps_ravi_and_removes_everyone_else_with_their_files(client):
    from pathlib import Path

    from app.db import SessionLocal
    from app.models import Document, Patient
    from app.seed import purge_patients_except

    pid = _register(client)["patient"]["id"]
    _sign_consult(client, pid)
    db = SessionLocal()
    try:
        note_file = Path(db.query(Document).filter(Document.patient_id == pid).first().path)
        assert note_file.is_file()
        assert purge_patients_except(db, {"pat_ravi"}) == [pid]
        assert [p.id for p in db.query(Patient).all()] == ["pat_ravi"]
        assert not note_file.exists()
    finally:
        db.close()
    assert [e for e in client.get("/api/patients/pat_ravi/timeline?limit=10").json()["events"]]
