"""Voice upload on Notes (T3), the shared VoiceInput (T5), auto-draft (T4a) and the Labs-tab upload (T6).

OpenAI is never called: every test that reaches the transcription step uses a fake client, and the
conftest sets an empty key, so a rejection test that did not install the fake would hit the key check
instead. Rejection tests therefore install the key and the fake, and assert the detail text and that
the fake was never called.

Frontend behaviour has no test runner here (see the manual steps in RESULT.md); the T5 and T6 rules
that can be checked by reading the source are checked below.
"""

from __future__ import annotations

import io
import re
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditEntry
from app.services.llm import DraftGenerationError

from fastapi import HTTPException

from .helpers import ASTHMA, FakePipeline, discharge, text_pdf

DOCTOR = {"X-User-Id": "u_meera"}
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
MB = 1024 * 1024
SENTENCE = "The patient has had a dry cough for two weeks."

LAB = [
    "CITY LAB REPORT",
    "Collected: 03 Sep 2026 07:40",
    "Creatinine 1.0 mg/dL (0.7-1.3)",
    "Potassium 4.1 mmol/L (3.5-5.1)",
]


# ---------- helpers ----------

def _consent(client):
    response = client.post(
        "/api/patients/pat_ravi/consents",
        json={"consent_type": "consultation_capture", "granted": True, "note": "test"},
        headers=DOCTOR,
    )
    assert response.status_code == 200, response.text


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


def _wav(seconds=0.1):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buffer.getvalue()


def _post(client, filename, content, content_type):
    return client.post("/api/notes/transcribe", files={"file": (filename, content, content_type)}, headers=DOCTOR)


@pytest.fixture()
def keyed(monkeypatch):
    return FakePipeline().install(monkeypatch)


def _assert_nothing_spent(client, before_balance, before_ledger, fake):
    assert _balance(client) == before_balance
    assert len(_ledger(client)) == before_ledger
    assert fake.calls == 0, "the pipeline must not be called for a refused upload"
    assert _audit("consultation_submitted") == []


# ---------- T3: upload a voice file ----------

def test_a_wav_upload_returns_the_transcript_and_passes_the_file_through(fresh, keyed):
    _consent(fresh)
    audio = _wav()
    response = _post(fresh, "visit.wav", audio, "audio/wav")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running" and response.json()["audio_id"]
    name, body, content_type = keyed.last_file
    assert (name, body, content_type) == ("visit.wav", audio, "audio/wav")


def test_upload_without_consent_is_refused_with_the_recording_message_and_costs_nothing(fresh, keyed):
    before, ledger = _balance(fresh), len(_ledger(fresh))
    response = _post(fresh, "visit.wav", _wav(), "audio/wav")
    assert response.status_code == 403
    assert response.json()["detail"] == "Record patient consent before capturing audio"
    _assert_nothing_spent(fresh, before, ledger, keyed)


def test_a_pdf_is_refused_as_not_audio_and_costs_nothing(fresh, keyed):
    _consent(fresh)
    before, ledger = _balance(fresh), len(_ledger(fresh))
    response = _post(fresh, "report.pdf", text_pdf(["Creatinine 1.0 mg/dL"]), "application/pdf")
    assert response.status_code == 415
    assert "not audio" in response.json()["detail"]
    _assert_nothing_spent(fresh, before, ledger, keyed)


def test_a_pdf_that_claims_to_be_audio_is_still_refused(fresh, keyed):
    _consent(fresh)
    before, ledger = _balance(fresh), len(_ledger(fresh))
    response = _post(fresh, "report.pdf", b"%PDF-1.4", "audio/wav")
    assert response.status_code == 415
    _assert_nothing_spent(fresh, before, ledger, keyed)


def test_audio_over_64_mb_is_refused_with_a_clear_message_and_costs_nothing(fresh, keyed):
    _consent(fresh)
    before, ledger = _balance(fresh), len(_ledger(fresh))
    response = _post(fresh, "long.wav", b"\x00" * (64 * MB + 1), "audio/wav")
    assert response.status_code == 413
    assert response.json()["detail"] == "Audio too large (max 64 MB)"
    _assert_nothing_spent(fresh, before, ledger, keyed)


def test_audio_of_exactly_64_mb_is_accepted(fresh, keyed):
    _consent(fresh)
    response = _post(fresh, "limit.wav", b"\x00" * (64 * MB), "audio/wav")
    assert response.status_code == 200, response.text


def test_an_empty_file_is_refused_and_costs_nothing(fresh, keyed):
    _consent(fresh)
    before, ledger = _balance(fresh), len(_ledger(fresh))
    response = _post(fresh, "empty.wav", b"", "audio/wav")
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]
    _assert_nothing_spent(fresh, before, ledger, keyed)


@pytest.mark.parametrize(
    "filename,content_type",
    [
        ("visit.webm", "audio/webm;codecs=opus"),
        ("visit.webm", "video/webm"),  # Chrome types a picked .webm as video
        ("visit.m4a", "audio/x-m4a"),
        ("visit.ogg", "application/octet-stream"),
        ("visit.mp3", "audio/mpeg"),
        ("consultation", "audio/webm"),  # no extension: the declared type decides
    ],
)
def test_the_usual_browser_audio_types_are_accepted(fresh, keyed, filename, content_type):
    _consent(fresh)
    response = _post(fresh, filename, b"not really audio", content_type)
    assert response.status_code == 200, response.text


def test_an_extensionless_non_audio_file_is_refused(fresh, keyed):
    _consent(fresh)
    response = _post(fresh, "report", b"data", "application/pdf")
    assert response.status_code == 415


def test_each_successful_upload_is_audited_once_and_charged_two_credits(fresh, keyed):
    _consent(fresh)
    before = _balance(fresh)
    assert _post(fresh, "visit.wav", _wav(), "audio/wav").status_code == 200
    assert before - _balance(fresh) == 2
    voice = [row for row in _ledger(fresh) if row["operation"] == "voice_note"]
    assert len(voice) == 1 and voice[0]["units"] == 2 and voice[0]["feature"] == "F1"
    assert len(_audit("consultation_submitted")) == 1
    assert _post(fresh, "visit2.wav", _wav(), "audio/wav").status_code == 200
    assert len(_audit("consultation_submitted")) == 2
    assert before - _balance(fresh) == 4


def test_a_pipeline_failure_charges_and_audits_nothing(fresh, keyed):
    _consent(fresh)
    before, ledger = _balance(fresh), len(_ledger(fresh))
    keyed.error = HTTPException(502, "Could not reach the MediBytes pipeline")
    assert _post(fresh, "visit.wav", _wav(), "audio/wav").status_code == 502
    assert _balance(fresh) == before and len(_ledger(fresh)) == ledger
    assert _audit("consultation_submitted") == []


def test_without_a_key_upload_is_refused_and_costs_nothing(fresh):
    _consent(fresh)
    before = _balance(fresh)
    response = _post(fresh, "visit.wav", _wav(), "audio/wav")
    assert response.status_code == 400 and "MEDIBYTES_API_KEY" in response.json()["detail"]
    assert _balance(fresh) == before


def test_after_discharge_transcribe_is_locked_before_any_charge(client, keyed):
    _consent(client)
    assert discharge(client, override={"reason": "Test discharge with open alerts"}).status_code == 200
    before, ledger = _balance(client), len(_ledger(client))
    response = _post(client, "visit.wav", _wav(), "audio/wav")
    assert response.status_code == 409 and "locked" in response.json()["detail"]
    assert _balance(client) == before and len(_ledger(client)) == ledger
    assert keyed.calls == 0


# ---------- T4a: the draft that follows a transcript (the calls the page makes in order) ----------

def _drafts(client):
    return client.get("/api/drafts?feature=F1&limit=50", headers=DOCTOR).json()["drafts"]


def _event_types(client):
    rows = client.get("/api/patients/pat_ravi/timeline?limit=500", headers=DOCTOR).json()["events"]
    return [row["type"] for row in rows]


def _poll(client, audio_id):
    return client.get(f"/api/notes/transcribe/{audio_id}", headers=DOCTOR)


def test_the_pipeline_note_becomes_a_draft_only_never_approved_and_no_note_on_the_timeline(fresh, keyed):
    _consent(fresh)
    before_types = _event_types(fresh)
    assert _drafts(fresh) == []
    audio_id = _post(fresh, "visit.wav", _wav(), "audio/wav").json()["audio_id"]
    polled = _poll(fresh, audio_id)
    assert polled.status_code == 200, polled.text
    body = polled.json()
    assert body["status"] == "succeeded"
    draft = body["draft"]
    assert draft["status"] == "draft_ready" and not draft.get("approved_by")
    content = draft["content"]
    assert content["hpi"]["text"].startswith("Swelling and redness")
    assert [c["text"] for c in content["plan"]] == ["IV cefazolin 2 g", "Complete blood count"]
    assert content["needs_review"] == [{"section": "Plan of management", "text": "Complete blood count"}]
    added = list(_event_types(fresh))
    for t in before_types:
        added.remove(t)
    assert added == ["transcript"], "only the hidden input event is written; no consult_note before approval"
    # Polling again returns the same draft instead of making another.
    assert _poll(fresh, audio_id).json()["draft"]["id"] == draft["id"]
    assert len(_drafts(fresh)) == 1


def test_a_pipeline_draft_cites_real_segments_and_can_be_approved(fresh, keyed):
    _consent(fresh)
    audio_id = _post(fresh, "visit.wav", _wav(), "audio/wav").json()["audio_id"]
    draft = _poll(fresh, audio_id).json()["draft"]
    response = fresh.post(f"/api/drafts/{draft['id']}/approve", json={}, headers=DOCTOR)
    assert response.status_code == 200, response.text


def test_a_running_or_failed_job_makes_no_draft(fresh, keyed):
    _consent(fresh)
    audio_id = _post(fresh, "visit.wav", _wav(), "audio/wav").json()["audio_id"]
    keyed.job_status = "running"
    assert _poll(fresh, audio_id).json() == {"status": "running"}
    keyed.job_status, keyed.job_error = "failed", "Recording too short"
    assert _poll(fresh, audio_id).json() == {"status": "failed", "error": "Recording too short"}
    assert _drafts(fresh) == []


def test_the_draft_still_needs_the_approval_step_and_consent(fresh, keyed):
    draft = fresh.post("/api/notes/generate", json={"feature": "F1", "transcript": ASTHMA}, headers=DOCTOR).json()["draft"]
    response = fresh.post(f"/api/drafts/{draft['id']}/approve", json={}, headers=DOCTOR)
    assert response.status_code == 400 and "consent" in response.json()["detail"].lower()
    assert "consult_note" not in _event_types(fresh)


def test_without_consent_there_is_no_transcript_and_so_no_draft(fresh, keyed):
    response = _post(fresh, "visit.wav", _wav(), "audio/wav")
    assert response.status_code == 403
    assert _drafts(fresh) == [] and keyed.calls == 0


def test_after_discharge_no_draft_is_produced(client, keyed):
    _consent(client)
    assert discharge(client, override={"reason": "Test discharge with open alerts"}).status_code == 200
    before = len(_drafts(client))
    assert _post(client, "visit.wav", _wav(), "audio/wav").status_code == 409
    response = client.post("/api/notes/generate", json={"feature": "F1", "transcript": ASTHMA}, headers=DOCTOR)
    assert response.status_code == 409
    assert len(_drafts(client)) == before


def test_a_transcript_shorter_than_ten_characters_cannot_be_drafted(fresh):
    response = fresh.post("/api/notes/generate", json={"feature": "F1", "transcript": "ok"}, headers=DOCTOR)
    assert response.status_code == 422  # the page checks the same limit and does not call generate


# ---------- T5: one shared VoiceInput; the source tree proves it ----------

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


def test_voice_input_shows_record_and_upload_together():
    source = _source("components/VoiceInput.tsx")
    assert "Record audio" in source and "Upload voice" in source
    assert 'type="file"' in source and "audio/*" in source
    assert "Record patient consent before capturing audio." in source


def test_only_the_f1_tab_gets_voice_input():
    notes = _source("pages/Notes.tsx")
    assert notes.count("<VoiceInput") == 1
    start = notes.index('tab.feature === "F1" ? (\n                  <div className={`banner')
    end = notes.index("{transcribing || pendingDraft")
    assert start < notes.index("<VoiceInput") < end, "VoiceInput must sit inside the F1 consent banner only"


def test_the_stale_whisper_in_production_line_is_gone():
    assert "Whisper in production" not in _source("pages/Notes.tsx")
    assert "Whisper in live mode" not in _source("pages/Notes.tsx")


def test_typed_transcripts_still_draft_and_voice_hands_over_a_pipeline_draft():
    notes = _source("pages/Notes.tsx")
    assert "onDraft={onVoiceDraft}" in notes
    assert "override?.text ?? transcript" in notes
    assert "Transcribing..." in notes and "Drafting..." in notes


# ---------- T6: upload a lab report from the Labs tab ----------

def test_the_labs_tab_reuses_upload_report_and_the_documents_permission():
    notes = _source("pages/Notes.tsx")
    assert 'import { uploadReport } from "../features/f08/upload";' in notes
    assert 'uploadReport(file, "lab_report")' in notes
    assert "/documents/upload" not in notes and "uploadDocument" not in notes, "no second upload path"
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
    assert before - _balance(fresh) == 1  # report_reading, the same as an F8 upload
    listed = fresh.get("/api/documents", headers=DOCTOR).json()["documents"]
    assert document["id"] in [item["id"] for item in listed]
    assert listed[0]["id"] == document["id"], "the newest document is first, so Documents opens on it"
    # Once committed (by hand, or already by the automatic save) the values are unreviewed lab rows.
    if document["ocr_status"] != "confirmed":
        committed = fresh.post(f"/api/documents/{document['id']}/commit", headers=DOCTOR)
        assert committed.status_code == 200, committed.text
    labs = fresh.get("/api/investigations", headers=DOCTOR).json()["labs"]
    by_name = {lab["name"]: lab for lab in labs}
    assert {"Creatinine", "Potassium"} <= set(by_name)
    assert all(by_name[name]["review_status"] == "unreviewed" for name in ("Creatinine", "Potassium"))
