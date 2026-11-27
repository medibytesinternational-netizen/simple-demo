"""Daily progress notes use the shared API flow and stay in review until signed."""

from __future__ import annotations

from .helpers import FakeMediBytesHTTP


def _consent(client, headers):
    response = client.post(
        "/api/patients/pat_ravi/consents",
        json={"consent_type": "consultation_capture", "granted": True, "note": "test"},
        headers={"X-User-Id": "u_meera"},
    )
    assert response.status_code == 200, response.text


def _record(client, fake, role="", headers=None, texts=("Afebrile since morning", "Tolerating oral feeds")):
    headers = headers or {"X-User-Id": "u_meera"}
    _consent(client, headers)
    meta = client.get("/api/meta", headers=headers).json()
    note = {
        "present_illness": ". ".join(texts) + ".",
        "examination_findings": "",
        "previous_diagnosis": "",
        "plan_of_management": "",
        "diet_instructions": "",
        "general_instructions": "",
    }
    form = {"feature": "F4"}
    if role:
        form["role"] = role
    sent = client.post(
        f"/api/notes/transcribe?encounter_id={meta['encounter']['id']}",
        files={"file": ("p.webm", b"abc", "audio/webm")},
        data=form,
        headers=headers,
    )
    assert sent.status_code == 200, sent.text
    audio_id = sent.json()["audio_id"]
    fake.set_success(audio_id, note)
    checked = client.get(
        f"/api/notes/transcriptions/{audio_id}?encounter_id={meta['encounter']['id']}", headers=headers
    )
    assert checked.status_code == 200, checked.text
    draft = checked.json()["draft"]
    assert draft["status"] == "draft_ready"
    assert draft["content"]["format"] == "progress_v2"
    signed = client.post(f"/api/drafts/{draft['id']}/approve", json={}, headers=headers)
    assert signed.status_code == 200, signed.text
    event_id = signed.json()["event"]["id"]
    row = next(row for row in client.get("/api/progress-notes", headers=headers).json()["entries"] if row["event_id"] == event_id)
    return row


def test_a_doctor_recording_becomes_a_reviewable_draft_then_a_signed_row(client, monkeypatch):
    fake = FakeMediBytesHTTP().install(monkeypatch)
    row = _record(client, fake)
    assert row["role"] == "doctor" and row["signed_by"] == "Dr. Meera Shah"
    assert row["notes"] == "Afebrile since morning.\nTolerating oral feeds."
    events = client.get("/api/patients/pat_ravi/timeline?limit=200").json()["events"]
    assert any(e["id"] == row["event_id"] and e["type"] == "progress_note" for e in events)


def test_every_days_entry_stays(client, monkeypatch):
    fake = FakeMediBytesHTTP().install(monkeypatch)
    first = _record(client, fake)
    second = _record(client, fake, texts=("Walking in the ward",))
    rows = client.get("/api/progress-notes").json()["entries"]
    assert [row["event_id"] for row in rows] == [first["event_id"], second["event_id"]]


def test_doctors_and_nurses_share_one_table_with_their_names(client, monkeypatch):
    fake = FakeMediBytesHTTP().install(monkeypatch)
    doctor = _record(client, fake)
    nurse = _record(client, fake, headers={"X-User-Id": "u_anita"})
    rows = client.get("/api/progress-notes").json()["entries"]
    assert [(r["event_id"], r["signed_by"]) for r in rows] == [
        (doctor["event_id"], "Dr. Meera Shah"), (nurse["event_id"], "Nurse Anita Rao")]


def test_each_role_writes_only_its_own_table(client, monkeypatch):
    FakeMediBytesHTTP().install(monkeypatch)
    upload = {"file": ("p.webm", b"abc", "audio/webm")}
    junior = {"X-User-Id": "u_kiran"}
    nurse = {"X-User-Id": "u_anita"}
    _consent(client, junior)
    _consent(client, nurse)
    meta = client.get("/api/meta", headers=junior).json()
    url = f"/api/notes/transcribe?encounter_id={meta['encounter']['id']}"
    assert client.post(url, files=upload, data={"feature": "F4", "role": "nurse"}, headers=junior).status_code == 403
    assert client.post(url, files=upload, data={"feature": "F4", "role": "doctor"}, headers=nurse).status_code == 403
    admin = {"X-User-Id": "u_meera"}
    _consent(client, admin)
    response = client.post(url, files=upload, data={"feature": "F4", "role": "nurse"}, headers=admin)
    assert response.status_code == 200, response.text


def test_the_report_prints_the_hospital_format(client, monkeypatch):
    fake = FakeMediBytesHTTP().install(monkeypatch)
    assert client.post("/api/progress-notes/report").status_code == 400
    doctor = _record(client, fake, texts=("Afebrile <b>since</b> morning",))
    nurse = _record(client, fake, headers={"X-User-Id": "u_anita"}, texts=("Vitals stable",))
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
    fake = FakeMediBytesHTTP().install(monkeypatch)
    _record(client, fake)
    pid = client.post("/api/patients", json={"name": "Lata Iyer", "age": 50, "sex": "Female", "no_known_allergies": True}).json()["patient"]["id"]
    assert client.get("/api/progress-notes", headers={"X-Patient-Id": pid}).json()["entries"] == []
