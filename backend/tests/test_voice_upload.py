"""Consent-gated MediBytes uploads, callbacks, status recovery and the Labs-tab upload."""

from __future__ import annotations

import io
import json
import re
import wave
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditEntry, Encounter, Patient, TimelineEvent
from app.models_ext.transcription import TranscriptionJob
from app.services.medibytes_note import format_note_sections

from .helpers import FakeMediBytesHTTP, discharge, text_pdf

DOCTOR = {"X-User-Id": "u_meera"}
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
MB = 1024 * 1024
CALLBACK_TOKEN = "callback-test-token"
NOTE_CONTENT = {
    "present_illness": "Test symptom reported for two days.",
    "examination_findings": "Test finding documented.",
    "previous_diagnosis": "",
    "plan_of_management": "Review at follow-up.",
    "diet_instructions": "",
    "general_instructions": "Return for the scheduled review.",
}
NOTE_RESPONSE = json.dumps([NOTE_CONTENT], ensure_ascii=False, separators=(",", ":"))
SENTENCE = format_note_sections(NOTE_CONTENT)
LAB = [
    "CITY LAB REPORT",
    "Collected: 03 Sep 2026 07:40",
    "Creatinine 1.0 mg/dL (0.7-1.3)",
    "Potassium 4.1 mmol/L (3.5-5.1)",
]


def _wav(seconds=0.1):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buffer.getvalue()


def _encounter_id(client):
    return client.get("/api/meta", headers=DOCTOR).json()["encounter"]["id"]


def _consent(client):
    response = client.post(
        "/api/patients/pat_ravi/consents",
        json={"consent_type": "consultation_capture", "granted": True, "note": "test"},
        headers=DOCTOR,
    )
    assert response.status_code == 200, response.text


def _post(client, filename="visit.wav", content=None, content_type="audio/wav", *, audio_id=None, encounter_id=None):
    query = f"?encounter_id={encounter_id or _encounter_id(client)}"
    if audio_id:
        query += f"&audio_id={audio_id}"
    return client.post(
        f"/api/notes/transcribe{query}",
        files={"file": (filename, content if content is not None else _wav(), content_type)},
        headers=DOCTOR,
    )


def _balance(client):
    return client.get("/api/credits", headers=DOCTOR).json()["balance"]


def _ledger(client):
    return client.get("/api/credits", headers=DOCTOR).json()["ledger"]


def _audit(action):
    db = SessionLocal()
    try:
        return list(db.scalars(select(AuditEntry).where(AuditEntry.action == action)).all())
    finally:
        db.close()


@pytest.fixture()
def medibytes(monkeypatch):
    return FakeMediBytesHTTP(callback_token=CALLBACK_TOKEN).install(monkeypatch)


def _callback(client, audio_id, response=NOTE_RESPONSE, *, token=CALLBACK_TOKEN, company_id=7, needs_review=None):
    return client.post(
        "/api/transcriptions/callback",
        json={"audio_id": audio_id, "company_id": company_id, "response": response, **({"needs_review": needs_review} if needs_review is not None else {})},
        headers={"Authorization": f"Bearer {token}"},
    )


def _jobs(client, encounter_id=None):
    encounter_id = encounter_id or _encounter_id(client)
    return client.get(f"/api/notes/transcriptions?encounter_id={encounter_id}", headers=DOCTOR).json()["transcriptions"]


def _event_types(client, encounter_id=None):
    query = f"?encounter_id={encounter_id}" if encounter_id else ""
    return [row["type"] for row in client.get(f"/api/patients/pat_ravi/timeline{query}&limit=500" if query else "/api/patients/pat_ravi/timeline?limit=500", headers=DOCTOR).json()["events"]]


def test_upload_requires_consent_and_does_not_spend_credits(fresh, medibytes):
    before = _balance(fresh)
    response = _post(fresh)
    assert response.status_code == 403
    assert response.json()["detail"] == "Record patient consent before capturing audio"
    assert medibytes.calls == []
    assert _balance(fresh) == before


def test_upload_requires_medybytes_credentials(fresh, medibytes, monkeypatch):
    _consent(fresh)
    medibytes.settings.medibytes_api_key = ""
    response = _post(fresh)
    assert response.status_code == 503
    assert "MEDIBYTES_API_KEY" in response.json()["detail"]
    assert medibytes.calls == []


@pytest.mark.parametrize("filename,content_type", [("visit.pdf", "audio/wav"), ("scan", "application/pdf")])
def test_non_audio_uploads_are_refused(fresh, medibytes, filename, content_type):
    _consent(fresh)
    response = _post(fresh, filename, b"not-audio", content_type)
    assert response.status_code == 415
    assert medibytes.calls == []


def test_empty_and_over_64mb_audio_are_refused(fresh, medibytes):
    _consent(fresh)
    assert _post(fresh, "empty.wav", b"").status_code == 400
    response = _post(fresh, "large.wav", b"0" * (64 * MB + 1))
    assert response.status_code == 413
    assert "64 MB" in response.json()["detail"]
    assert medibytes.calls == []


def test_audio_upload_is_multipart_associated_and_charged_once(fresh, medibytes):
    _consent(fresh)
    before = _balance(fresh)
    audio = _wav()
    response = _post(fresh, "consult.webm", audio, "video/webm", audio_id="consult-1")
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["audio_id"], body["job_status"], body["transcript"]) == ("consult-1", "queued", None)
    call = medibytes.calls[0]
    assert call == ("consult-1", 7, "consult.webm", "video/webm", audio)
    assert before - _balance(fresh) == 2

    # Repeating a request with the same id returns the existing queued job without another upload.
    repeated = _post(fresh, "consult.webm", audio, "video/webm", audio_id="consult-1")
    assert repeated.status_code == 200
    assert len(medibytes.calls) == 1
    assert before - _balance(fresh) == 2


def test_server_generates_unique_audio_ids(fresh, medibytes):
    _consent(fresh)
    first = _post(fresh).json()["audio_id"]
    second = _post(fresh).json()["audio_id"]
    assert first != second
    assert re.fullmatch(r"[A-Za-z0-9-]{1,64}", first)


def test_callback_parses_and_saves_all_six_note_sections_idempotently(fresh, medibytes):
    _consent(fresh)
    encounter_id = _encounter_id(fresh)
    submitted = _post(fresh, audio_id="visit-1")
    assert submitted.status_code == 200
    before_events = len(_event_types(fresh, encounter_id))
    callback = _callback(fresh, "visit-1", NOTE_RESPONSE)
    assert callback.status_code == 200 and callback.json() == {"status": "Success"}
    duplicate_body = json.dumps([NOTE_CONTENT], ensure_ascii=False, indent=2)
    duplicate = _callback(fresh, "visit-1", duplicate_body)
    assert duplicate.status_code == 200 and duplicate.json() == {"status": "Success"}

    rows = _jobs(fresh, encounter_id)
    assert rows[0]["transcript"] == SENTENCE
    assert rows[0]["note_content"] == NOTE_CONTENT
    assert rows[0]["response"] == NOTE_RESPONSE
    assert rows[0]["job_status"] == "succeeded"
    assert rows[0]["transcript_event_id"]
    assert len(_event_types(fresh, encounter_id)) == before_events + 1
    assert len(_audit("consultation_transcribed")) == 1
    assert before_events - len(_event_types(fresh, encounter_id)) == -1
    event = fresh.get(f"/api/events/{rows[0]['transcript_event_id']}", headers=DOCTOR).json()
    assert event["source"] == "medibytes"
    assert event["author_name"] == "MediBytes Transcription API"
    assert event["payload"]["note_content"] == NOTE_CONTENT


def test_review_warnings_are_saved_for_the_screen_draft(fresh, medibytes):
    _consent(fresh)
    _post(fresh, audio_id="review-1")
    warnings = [{"section": "plan_of_management", "text": "Check the dose in this instruction."}]
    assert _callback(fresh, "review-1", needs_review=warnings).json() == {"status": "Success"}
    job = _jobs(fresh)[0]
    status = fresh.get(f"/api/notes/transcriptions/review-1?encounter_id={job['encounter_id']}", headers=DOCTOR).json()
    assert status["draft"]["content"]["needs_review"] == warnings


def test_callback_authentication_unknown_id_and_company_scope(fresh, medibytes):
    assert _callback(fresh, "unknown", token="wrong").status_code == 401
    unknown = _callback(fresh, "unknown")
    assert unknown.status_code == 200 and unknown.json()["status"] == "Failed"
    _consent(fresh)
    assert _post(fresh, audio_id="visit-2").status_code == 200
    mismatch = _callback(fresh, "visit-2", company_id=8)
    assert mismatch.status_code == 200 and mismatch.json()["status"] == "Failed"
    assert _jobs(fresh)[0]["transcript"] is None


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        "[]",
        "[{}]",
        json.dumps([{**NOTE_CONTENT, "examination_findings": 12}]),
        json.dumps([NOTE_CONTENT, NOTE_CONTENT]),
    ],
)
def test_invalid_note_payload_is_rejected_in_medybytes_failure_body(fresh, medibytes, response):
    _consent(fresh)
    _post(fresh, audio_id="bad-note-1")
    result = _callback(fresh, "bad-note-1", response)
    assert result.status_code == 200
    assert result.json()["status"] == "Failed"
    assert result.json()["Message"]
    row = _jobs(fresh)[0]
    assert row["note_content"] is None and row["transcript_event_id"] is None


def test_all_empty_note_sections_are_saved_without_filling_missing_information(fresh, medibytes):
    _consent(fresh)
    _post(fresh, audio_id="empty-note-1")
    empty_note = {field: "" for field in NOTE_CONTENT}
    result = _callback(fresh, "empty-note-1", json.dumps([empty_note]))
    assert result.status_code == 200 and result.json() == {"status": "Success"}
    row = _jobs(fresh)[0]
    assert row["note_content"] == empty_note
    assert row["transcript_event_id"]


def test_status_check_tracks_running_and_saves_transcript_from_status_if_callback_is_missing(fresh, medibytes):
    _consent(fresh)
    uploaded = _post(fresh, audio_id="status-1").json()
    running = medibytes.statuses["status-1"]
    running["job_status"] = "running"
    checked = fresh.get(f"/api/notes/transcriptions/status-1?encounter_id={uploaded['encounter_id']}", headers=DOCTOR)
    assert checked.status_code == 200 and checked.json()["job_status"] == "running"

    running["job_status"] = "succeeded"
    running["response"] = NOTE_RESPONSE
    running["delivery"] = {"state": "delivered", "attempts": 1, "last_http_status": 200, "last_error": None, "hims_reply": '{"status":"Success"}', "delivered_at": "2026-11-23T10:00:00Z", "next_attempt_at": None}
    checked = fresh.get(f"/api/notes/transcriptions/status-1?encounter_id={uploaded['encounter_id']}", headers=DOCTOR)
    assert checked.status_code == 200
    assert checked.json()["transcript"] == SENTENCE
    assert checked.json()["note_content"] == NOTE_CONTENT
    assert checked.json()["delivery"]["state"] == "delivered"
    assert checked.json()["delivery"]["attempts"] == 1
    assert len(_audit("consultation_transcribed")) == 1


@pytest.mark.parametrize(
    "response,expected_error",
    [
        (None, "has not returned a transcript yet"),
        ("plain speech transcript", "not valid JSON"),
    ],
)
def test_status_succeeded_without_documented_note_shape_is_reported_not_fabricated(
    fresh, medibytes, response, expected_error
):
    _consent(fresh)
    uploaded = _post(fresh, audio_id="missing-note-1").json()
    payload = medibytes.statuses["missing-note-1"]
    payload["job_status"] = "succeeded"
    payload["response"] = response
    checked = fresh.get(
        f"/api/notes/transcriptions/missing-note-1?encounter_id={uploaded['encounter_id']}",
        headers=DOCTOR,
    )
    assert checked.status_code == 200, checked.text
    result = checked.json()
    assert result["job_status"] == "succeeded"
    assert expected_error in result["job_error"]
    assert result["note_content"] is None
    assert result["transcript_event_id"] is None


def test_status_timeout_is_reported_without_losing_local_job(fresh, medibytes, monkeypatch):
    _consent(fresh)
    uploaded = _post(fresh, audio_id="timeout-1").json()

    medibytes.failure_status = 504
    response = fresh.get(f"/api/notes/transcriptions/timeout-1?encounter_id={uploaded['encounter_id']}", headers=DOCTOR)
    assert response.status_code == 200
    assert "HTTP 504" in response.json()["status_check_error"]
    assert response.json()["audio_id"] == "timeout-1"


def test_redelivery_only_runs_after_medybytes_marks_delivery_failed(fresh, medibytes):
    _consent(fresh)
    uploaded = _post(fresh, audio_id="redeliver-1").json()
    path = f"/api/notes/transcriptions/redeliver-1/redeliver?encounter_id={uploaded['encounter_id']}"
    assert fresh.post(path, headers=DOCTOR).status_code == 409

    payload = medibytes.statuses["redeliver-1"]
    payload["job_status"] = "succeeded"
    payload["response"] = NOTE_RESPONSE
    payload["delivery"] = {"state": "failed", "attempts": 1, "last_http_status": 403, "last_error": "Unauthorized", "hims_reply": None, "delivered_at": None, "next_attempt_at": "2026-11-23T10:00:00Z"}
    response = fresh.post(path, headers=DOCTOR)
    assert response.status_code == 200, response.text
    assert response.json()["delivery"]["state"] == "pending"
    assert response.json()["transcript"] == SENTENCE
    assert response.json()["note_content"] == NOTE_CONTENT
    assert response.json()["delivery"]["next_attempt_at"] is None


def test_cross_consultation_transcripts_are_not_loaded_or_generated(fresh, medibytes):
    _consent(fresh)
    db = SessionLocal()
    try:
        other_patient = Patient(id="pat_other_test", mrn="OTHER-1", name="Other Patient", age=40, sex="F")
        other_encounter = Encounter(id="enc_other_test", patient_id=other_patient.id, status="active")
        db.add_all([other_patient, other_encounter])
        db.commit()
    finally:
        db.close()

    response = _post(fresh, audio_id="wrong-scope", encounter_id="enc_other_test")
    assert response.status_code == 404
    assert medibytes.calls == []
    assert fresh.get("/api/notes/transcriptions?encounter_id=enc_other_test", headers=DOCTOR).status_code == 404


def test_audio_retry_reuses_id_after_a_missing_remote_job(fresh, medibytes, monkeypatch):
    _consent(fresh)
    uploaded = _post(fresh, audio_id="retry-1").json()
    status_path = f"/api/notes/transcriptions/retry-1?encounter_id={uploaded['encounter_id']}"
    del medibytes.statuses["retry-1"]
    missing = fresh.get(status_path, headers=DOCTOR).json()
    assert missing["job_status"] == "failed" and missing["can_retry_upload"]
    retried = _post(fresh, audio_id="retry-1")
    assert retried.status_code == 200
    assert len([call for call in medibytes.calls if call[0] == "retry-1"]) == 2
    assert _balance(fresh) == 4998


def test_draft_reuses_saved_transcript_event_without_duplicate(fresh, medibytes):
    _consent(fresh)
    encounter_id = _encounter_id(fresh)
    assert _post(fresh, audio_id="draft-1").status_code == 200
    assert _callback(fresh, "draft-1", NOTE_RESPONSE).status_code == 200
    transcript = _jobs(fresh, encounter_id)[0]
    response = fresh.post(
        f"/api/notes/generate?encounter_id={encounter_id}",
        json={"feature": "F1", "transcript": SENTENCE, "transcript_event_id": transcript["transcript_event_id"]},
        headers=DOCTOR,
    )
    assert response.status_code == 200, response.text
    assert response.json()["draft"]["created_from_event_ids"] == [transcript["transcript_event_id"]]
    mismatch = fresh.post(
        f"/api/notes/generate?encounter_id={encounter_id}",
        json={"feature": "F1", "transcript": "Different transcript text", "transcript_event_id": transcript["transcript_event_id"]},
        headers=DOCTOR,
    )
    assert mismatch.status_code == 404
    assert len([kind for kind in _event_types(fresh) if kind == "transcript"]) == 1


def test_after_discharge_transcribe_is_locked_before_any_charge(client, medibytes):
    _consent(client)
    assert discharge(client, override={"reason": "Test discharge with open alerts"}).status_code == 200
    before, ledger = _balance(client), len(_ledger(client))
    response = _post(client)
    assert response.status_code == 409 and "locked" in response.json()["detail"]
    assert _balance(client) == before and len(_ledger(client)) == ledger
    assert medibytes.calls == []


# ---------- Shared VoiceInput and OPD transcript loading ----------

def _source(path: str) -> str:
    return (FRONTEND / path).read_text(encoding="utf-8")


def _tsx_files():
    return [p for p in FRONTEND.rglob("*") if p.suffix in {".ts", ".tsx"}]


def test_media_recorder_and_get_user_media_exist_only_in_voice_input():
    for needle in ("MediaRecorder", "getUserMedia"):
        hits = sorted(p.relative_to(FRONTEND).as_posix() for p in _tsx_files() if needle in p.read_text(encoding="utf-8"))
        assert hits == ["components/VoiceInput.tsx"], f"{needle} found in {hits}"


def test_transcribe_audio_is_called_only_from_voice_input():
    callers = sorted(
        p.relative_to(FRONTEND).as_posix()
        for p in _tsx_files()
        if re.search(r"transcribeAudio\(", p.read_text(encoding="utf-8")) and p.name != "api.ts"
    )
    assert callers == ["components/VoiceInput.tsx"]


def test_voice_input_shows_record_upload_retry_and_polling_together():
    source = _source("components/VoiceInput.tsx")
    assert "Record audio" in source and "Upload voice" in source and "Retry upload" in source
    assert 'type="file"' in source and "audio/*" in source
    assert "getTranscription" in source and "MediBytes is transcribing" in source
    assert "Record patient consent before capturing audio." in source


def test_voice_screens_share_the_api_upload_path_and_keep_their_feature():
    notes = _source("pages/Notes.tsx")
    assert notes.count("<VoiceInput") == 2
    assert 'feature="F3"' in notes and "feature={tab.feature}" in notes
    assert 'feature="F4"' in _source("features/f04/ProgressNotes.tsx")
    assert 'feature="F11"' in _source("features/f11/ReferralForm.tsx")
    assert "intakeAudio(audio" in _source("pages/NewPatient.tsx")
    api_source = _source("api.ts")
    assert '`/notes/transcribe?encounter_id=' in api_source
    assert '`/notes/transcriptions/${encodeURIComponent(audioId)}?encounter_id=' in api_source
    assert '"/progress-notes/record"' not in api_source
    assert '"/referrals/record"' not in api_source


def test_intake_and_encounter_flows_poll_for_reviewable_templates():
    api_source = _source("api.ts")
    assert "TRANSCRIPTION_POLL_MS = 15_000" in api_source
    assert "status.draft" in api_source
    assert "generateVoiceDraft" in _source("features/f04/ProgressNotes.tsx")
    assert "generateVoiceDraft" in _source("features/f11/ReferralForm.tsx")


def test_legacy_transcription_provider_is_absent_from_runtime_sources():
    repository = Path(__file__).resolve().parents[2]
    runtime_roots = (repository / "backend" / "app", repository / "frontend" / "src")
    runtime_files = [
        path
        for root in runtime_roots
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".ts", ".tsx", ".js", ".jsx"}
    ]
    legacy_references = [
        str(path.relative_to(repository))
        for path in runtime_files
        if "whisper" in path.read_text(encoding="utf-8").lower()
    ]
    assert legacy_references == []


# ---------- Labs-tab upload ----------

def test_the_labs_tab_reuses_upload_report_and_the_documents_permission():
    notes = _source("pages/Notes.tsx")
    assert 'import { uploadReport } from "../features/f08/upload";' in notes
    assert 'uploadReport(file, "lab_report")' in notes
    assert "/documents/upload" not in notes and "uploadDocument" not in notes
    assert 'useCan("upload_document")' in notes
    assert "disabled={!canUpload" in notes
    assert "Upload lab report" in notes and "Review in Documents" in notes
    assert "12 * 1024 * 1024" in notes


def test_a_lab_pdf_uploaded_as_the_labs_tab_does_is_a_lab_report_document_charged_like_f8(fresh):
    before = _balance(fresh)
    response = fresh.post(
        "/api/documents/upload",
        files={"file": ("lab.pdf", text_pdf(LAB), "application/pdf")},
        data={"doc_type": "lab_report"},
        headers=DOCTOR,
    )
    assert response.status_code == 200, response.text
    document = response.json()
    assert document["doc_type"] == "lab_report"
    assert before - _balance(fresh) == 1
    listed = fresh.get("/api/documents", headers=DOCTOR).json()["documents"]
    assert document["id"] in [item["id"] for item in listed]
    assert listed[0]["id"] == document["id"]
    if document["ocr_status"] != "confirmed":
        committed = fresh.post(f"/api/documents/{document['id']}/commit", headers=DOCTOR)
        assert committed.status_code == 200, committed.text
    labs = fresh.get("/api/investigations", headers=DOCTOR).json()["labs"]
    by_name = {lab["name"]: lab for lab in labs}
    assert {"Creatinine", "Potassium"} <= set(by_name)
    assert all(by_name[name]["review_status"] == "unreviewed" for name in ("Creatinine", "Potassium"))
