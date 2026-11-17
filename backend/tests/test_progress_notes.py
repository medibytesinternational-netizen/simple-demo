"""Daily progress notes: doctor's and nurse's tables, filled by voice and signed by who recorded."""

from __future__ import annotations

from .helpers import FakePipeline

SAID = "Patient is afebrile since morning. Tolerating oral feeds."


def _note(*texts):
    return {"sections": {"notes": {"items": [
        {"text": t, "source_sentence": t + ".", "seg_id": 0, "confidence": 0.9} for t in texts
    ]}}}


def _record(client, fake, role="", headers=None, texts=("Afebrile since morning", "Tolerating oral feeds")):
    fake.transcript = SAID
    fake.note = _note(*texts)
    sent = client.post("/api/progress-notes/record", files={"file": ("p.webm", b"abc", "audio/webm")},
                       data={"role": role}, headers=headers or {})
    assert sent.status_code == 200, sent.text
    done = client.get(f"/api/progress-notes/record/{sent.json()['audio_id']}", headers=headers or {}).json()
    assert done["status"] == "succeeded", done
    return done["entry"]


def test_a_doctor_recording_becomes_a_signed_row_and_a_timeline_entry(client, monkeypatch):
    fake = FakePipeline().install(monkeypatch)
    entry = _record(client, fake)
    assert fake.feature == "F4"
    assert entry["role"] == "doctor" and entry["signed_by"] == "Dr. Meera Shah"
    assert entry["notes"] == "Afebrile since morning\nTolerating oral feeds"
    rows = client.get("/api/progress-notes").json()["entries"]
    assert [r["event_id"] for r in rows] == [entry["event_id"]] and rows[0]["signed_by"] == "Dr. Meera Shah"
    events = client.get("/api/patients/pat_ravi/timeline?limit=200").json()["events"]
    assert any(e["id"] == entry["event_id"] and e["type"] == "progress_note" for e in events)


def test_every_days_entry_stays(client, monkeypatch):
    fake = FakePipeline().install(monkeypatch)
    first = _record(client, fake)
    second = _record(client, fake, texts=("Walking in the ward",))
    rows = client.get("/api/progress-notes").json()["entries"]
    assert [r["event_id"] for r in rows] == [first["event_id"], second["event_id"]]


def test_doctors_and_nurses_share_one_table_with_their_names(client, monkeypatch):
    fake = FakePipeline().install(monkeypatch)
    doctor = _record(client, fake)
    nurse = _record(client, fake, headers={"X-User-Id": "u_anita"})
    assert nurse["role"] == "nurse" and nurse["signed_by"] == "Nurse Anita Rao"
    rows = client.get("/api/progress-notes").json()["entries"]
    assert [(r["event_id"], r["signed_by"]) for r in rows] == [
        (doctor["event_id"], "Dr. Meera Shah"), (nurse["event_id"], "Nurse Anita Rao")]


def test_each_role_writes_only_its_own_table(client, monkeypatch):
    FakePipeline().install(monkeypatch)
    upload = {"file": ("p.webm", b"abc", "audio/webm")}
    junior = client.post("/api/progress-notes/record", files=upload, data={"role": "nurse"}, headers={"X-User-Id": "u_kiran"})
    assert junior.status_code == 403
    nurse = client.post("/api/progress-notes/record", files=upload, data={"role": "doctor"}, headers={"X-User-Id": "u_anita"})
    assert nurse.status_code == 403
    admin = client.post("/api/progress-notes/record", files=upload, data={"role": "nurse"})
    assert admin.status_code == 200


def test_the_report_prints_the_hospital_format(client, monkeypatch):
    fake = FakePipeline().install(monkeypatch)
    assert client.post("/api/progress-notes/report").status_code == 400  # nothing to print yet
    _record(client, fake, texts=("Afebrile <b>since</b> morning",))
    _record(client, fake, headers={"X-User-Id": "u_anita"}, texts=("Vitals stable",))
    made = client.post("/api/progress-notes/report")
    assert made.status_code == 200, made.text
    page = client.get(f"/api/documents/{made.json()['document_id']}/file").text
    order = ["Name", "Sex", "Age", "Ward", "Bed", "UHID number", "Date and time", "Notes", "Name and sign"]
    positions = [page.index(label) for label in order]
    assert positions == sorted(positions)
    assert "Ravi Menon" in page and "Dr. Meera Shah" in page and "Nurse Anita Rao" in page and "<b>since</b>" not in page
    events = client.get("/api/patients/pat_ravi/timeline?limit=200").json()["events"]
    assert any(e["type"] == "progress_report" and e["document_id"] for e in events)


def test_another_patients_notes_are_not_shown(client, monkeypatch):
    fake = FakePipeline().install(monkeypatch)
    _record(client, fake)
    pid = client.post("/api/patients", json={"name": "Lata Iyer", "age": 50, "sex": "Female", "no_known_allergies": True}).json()["patient"]["id"]
    assert client.get("/api/progress-notes", headers={"X-Patient-Id": pid}).json()["entries"] == []
