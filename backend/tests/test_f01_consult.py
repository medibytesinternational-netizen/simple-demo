"""F1 ambient OPD documentation: the note comes from the conversation, with consent, for approval."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db import SessionLocal
from app.services import credits
from app.services.context import segments_from_transcript
from app.services.extract import analyse

from fastapi import HTTPException

from .helpers import ASTHMA, SHORT_VISIT, FakePipeline

CHEST = (
    "Doctor: What brings you in?\n"
    "Patient: I have had a cough for three days.\n"
    "Doctor: Any fever?\n"
    "Patient: Yes, I felt feverish last night.\n"
    "Doctor: Your temperature is 38.1 and your chest has crackles on the left.\n"
    "Doctor: I think this is a chest infection. Start amoxicillin 500 mg three times a day for five days.\n"
    "Doctor: Review in one week."
)
NO_EXAM = (
    "Doctor: What brings you in?\n"
    "Patient: I have had a sore throat for two days.\n"
    "Doctor: This looks like a viral throat infection. Take paracetamol 500 mg as needed.\n"
    "Doctor: Review in one week if it is not better."
)
EMPTY_NOTE = {
    "chief_complaint": None,
    "hpi": None,
    "exam": {"general": None, "systemic": None},
    "assessment": [],
    "plan": [],
    "medication_mentions": [],
    "follow_up": None,
    "not_documented": [],
}
REAL_NOTE = {
    **EMPTY_NOTE,
    "chief_complaint": {"text": "Dry cough and wheeze.", "source_event_ids": [], "source_segment_ids": ["seg_2"]},
}
USAGE = {"latency_ms": 1, "input_tokens": 2, "output_tokens": 3, "request_json": {}}


def _generate(client, transcript):
    response = client.post("/api/notes/generate", json={"feature": "F1", "transcript": transcript})
    assert response.status_code == 200, response.text
    return response.json()


def _claims(value, out=None):
    out = [] if out is None else out
    if isinstance(value, dict):
        if isinstance(value.get("text"), str) and "source_segment_ids" in value and "drug" not in value:
            out.append(value)
        for item in value.values():
            _claims(item, out)
    elif isinstance(value, list):
        for item in value:
            _claims(item, out)
    return out


def _only_quotes(text, transcript):
    """True when text is sentences the speakers said, in one run, with nothing else."""
    said = [sentence.text for sentence in analyse(segments_from_transcript(transcript)).sentences]
    rest = text.strip()
    while rest:
        for sentence in said:
            if rest.startswith(sentence):
                rest = rest[len(sentence):].strip()
                break
        else:
            return False
    return True


def _consent(client):
    response = client.post(
        "/api/patients/pat_ravi/consents",
        json={"consent_type": "consultation_capture", "granted": True, "note": "test"},
    )
    assert response.status_code == 200, response.text


def _balance(client):
    return client.get("/api/credits").json()["balance"]


def _live(monkeypatch, live_reply, repair_reply=None, repair_calls=None):
    """Make the model call return a canned reply, or raise, without any network."""
    monkeypatch.setattr(
        "app.services.llm.settings",
        SimpleNamespace(effective_llm_mode="live", openai_model="gpt-test", openai_api_key="sk-test"),
    )

    def live_call(feature, prompt, context, model_cls):
        if isinstance(live_reply, Exception):
            raise live_reply
        return dict(live_reply), dict(USAGE)

    def repair_call(feature, prompt, context, model_cls, errors):
        (repair_calls if repair_calls is not None else []).append(list(errors))
        if isinstance(repair_reply, Exception):
            raise repair_reply
        return dict(repair_reply if repair_reply is not None else live_reply), dict(USAGE)

    monkeypatch.setattr("app.services.llm._live_call", live_call)
    monkeypatch.setattr("app.services.llm._repair_call", repair_call)


# ---------- the note comes from the conversation (rule 2) and shows its evidence (rule 3) ----------

def test_every_claim_is_a_quote_that_cites_a_real_segment(client):
    result = _generate(client, ASTHMA)
    content = result["draft"]["content"]
    transcript_event = result["transcript_event_id"]
    segment_ids = {s["segment_id"] for s in segments_from_transcript(ASTHMA)}
    claims = _claims(content)
    assert len(claims) >= 5, "complaint, hpi, exam, assessment, plan and follow-up were all said"
    for claim in claims:
        assert claim["text"] in ASTHMA, claim["text"]
        assert claim["source_event_ids"] == [transcript_event]
        assert claim["source_segment_ids"] and set(claim["source_segment_ids"]) <= segment_ids
    assert "wheeze" in content["chief_complaint"]["text"]
    assert "mild persistent asthma" in content["assessment"][0]["text"]
    assert content["not_documented"] == []


def test_medicines_come_from_the_words_spoken_with_their_segment(client):
    content = _generate(client, ASTHMA)["draft"]["content"]
    meds = {m["drug"].lower(): m for m in content["medication_mentions"]}
    assert set(meds) == {"salbutamol", "beclometasone"}
    assert meds["beclometasone"]["dose"].lower() == "100 micrograms"
    assert meds["beclometasone"]["frequency"].lower() == "twice daily"
    assert meds["salbutamol"]["frequency"].lower() == "as needed"
    assert meds["salbutamol"]["source_segment_ids"] == ["seg_6"]


def test_a_multi_turn_visit_quotes_only_sentences_that_were_said(client):
    content = _generate(client, CHEST)["draft"]["content"]
    claims = _claims(content)
    assert any("cough" in c["text"] for c in claims)
    for claim in claims:
        assert _only_quotes(claim["text"], CHEST), claim["text"]
    # History is the patient's words across two turns; both turns are cited.
    assert content["hpi"]["text"] == "Yes, I felt feverish last night."
    assert content["exam"]["general"]["source_segment_ids"] == ["seg_5"]
    assert "chest infection" in content["assessment"][0]["text"]
    assert "amoxicillin" in " ".join(c["text"] for c in content["plan"])
    assert content["follow_up"]["text"] == "Review in one week."


def test_a_note_does_not_use_the_patient_record(client):
    # The demo patient has diabetes, CKD and a leg infection on file; none of it was said here.
    text = " ".join(c["text"] for c in _claims(_generate(client, ASTHMA)["draft"]["content"])).lower()
    for record_fact in ("cellulitis", "metformin", "diabetes", "ckd", "58-year-old", "egfr"):
        assert record_fact not in text


def test_a_consultation_with_no_exam_leaves_exam_empty_and_says_so(client):
    content = _generate(client, NO_EXAM)["draft"]["content"]
    assert content["exam"] == {"general": None, "systemic": None}
    assert "Examination" in content["not_documented"]
    assert content["assessment"] and "viral throat infection" in content["assessment"][0]["text"]


def test_a_visit_with_nothing_clinical_lists_every_missing_section(client):
    content = _generate(client, SHORT_VISIT)["draft"]["content"]
    assert content["assessment"] == [] and content["plan"] == [] and content["follow_up"] is None
    assert content["hpi"] is None
    assert {"Examination", "Assessment", "Plan", "History"} <= set(content["not_documented"])


def test_cached_mode_by_configuration_is_not_reported_as_a_fallback(client):
    llm = _generate(client, ASTHMA)["llm"]
    assert llm["mode"] == "cached"
    assert llm["fallback"] is False and llm["fallback_reason"] is None


# ---------- a live model that says nothing is not a finished note ----------

def test_empty_live_output_is_repaired_then_falls_back_with_a_reason(client, monkeypatch):
    repairs: list = []
    _live(monkeypatch, EMPTY_NOTE, repair_calls=repairs)
    result = _generate(client, ASTHMA)
    assert len(repairs) == 1 and "empty" in repairs[0][0].lower()
    llm = result["llm"]
    assert llm["fallback"] is True
    assert "empty note" in llm["fallback_reason"]
    assert llm["mode"] == "cached", "the call must not be labelled live when rules wrote the note"
    assert llm["model"] == "cached"
    content = result["draft"]["content"]
    assert "wheeze" in content["chief_complaint"]["text"]
    assert result["draft"]["model"] == "cached"
    from app.models import LLMCall

    db = SessionLocal()
    try:
        call = db.get(LLMCall, result["draft"]["llm_call_id"])
        assert any("empty note" in e for e in call.validation_errors)
        assert call.mode == "cached"
    finally:
        db.close()


def test_a_repair_that_returns_a_real_note_stays_live(client, monkeypatch):
    repairs: list = []
    _live(monkeypatch, EMPTY_NOTE, REAL_NOTE, repair_calls=repairs)
    result = _generate(client, ASTHMA)
    assert len(repairs) == 1
    assert result["llm"]["mode"] == "live" and result["llm"]["fallback"] is False
    assert result["draft"]["content"]["chief_complaint"]["text"] == "Dry cough and wheeze."


def test_a_repair_that_is_still_empty_falls_back(client, monkeypatch):
    repairs: list = []
    _live(monkeypatch, EMPTY_NOTE, EMPTY_NOTE, repair_calls=repairs)
    result = _generate(client, ASTHMA)
    assert len(repairs) == 1
    assert result["llm"]["fallback"] is True and result["llm"]["mode"] == "cached"
    assert "wheeze" in result["draft"]["content"]["chief_complaint"]["text"]


def test_a_failed_live_call_falls_back_with_a_reason_and_no_repair(client, monkeypatch):
    repairs: list = []
    _live(monkeypatch, TimeoutError("boom sk-secret"), repair_calls=repairs)
    result = _generate(client, ASTHMA)
    assert repairs == []
    llm = result["llm"]
    assert llm["fallback"] is True and llm["mode"] == "cached"
    assert "TimeoutError" in llm["fallback_reason"]
    assert "sk-secret" not in llm["fallback_reason"], "the model's error text must not reach the page"
    assert "wheeze" in result["draft"]["content"]["chief_complaint"]["text"]


def test_a_live_reply_in_the_wrong_format_falls_back_with_a_reason(client, monkeypatch):
    all_null = {key: None for key in EMPTY_NOTE}
    _live(monkeypatch, all_null)
    result = _generate(client, ASTHMA)
    assert result["llm"]["fallback"] is True
    assert "wrong format" in result["llm"]["fallback_reason"]
    assert result["llm"]["mode"] == "cached"


# ---------- approval checks the transcript, and records who wrote the note ----------

def test_a_draft_citing_a_segment_that_does_not_exist_cannot_be_approved(client):
    _consent(client)
    draft = _generate(client, ASTHMA)["draft"]
    content = draft["content"]
    content["chief_complaint"]["source_segment_ids"] = ["seg_99"]
    response = client.post(f"/api/drafts/{draft['id']}/approve", json={"content": content})
    assert response.status_code == 400
    assert "seg_99" in response.json()["detail"]
    after = client.get(f"/api/drafts/{draft['id']}").json()
    assert (after.get("draft") or after)["status"] != "approved"


def test_a_draft_citing_real_segments_is_approved_and_the_model_is_the_author(client):
    _consent(client)
    draft = _generate(client, ASTHMA)["draft"]
    response = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert response.status_code == 200, response.text
    event = response.json()["event"]
    assert event["author_name"] == "cached (v2)"
    assert event["author_type"] == "model"
    assert event["approved_by"] == "Dr. Meera Shah"
    assert response.json()["draft"]["approved_by"] == "Dr. Meera Shah"


def test_approval_still_needs_consent(client):  # guard
    client.post("/api/demo/reset?mode=start")
    draft = _generate(client, ASTHMA)["draft"]
    response = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert response.status_code == 400 and "consent" in response.json()["detail"].lower()


# ---------- audio needs consent, a key, and costs 2 credits only when it really runs ----------

def _audio():
    return {"file": ("visit.webm", b"not really audio", "audio/webm")}


def test_audio_without_consent_is_refused_and_costs_nothing(fresh):  # guard
    before = _balance(fresh)
    response = fresh.post("/api/notes/transcribe", files=_audio())
    assert response.status_code == 403
    assert _balance(fresh) == before


def test_audio_with_consent_but_no_key_is_refused_and_costs_nothing(fresh):
    _consent(fresh)
    before = _balance(fresh)
    response = fresh.post("/api/notes/transcribe", files=_audio())
    assert response.status_code == 400 and "OPENAI_API_KEY" in response.json()["detail"]
    assert _balance(fresh) == before


@pytest.fixture()
def keyed(monkeypatch):
    return FakePipeline().install(monkeypatch)


def test_a_transcription_that_runs_costs_a_voice_note_of_two_credits(fresh, keyed):
    _consent(fresh)
    before = _balance(fresh)
    response = fresh.post("/api/notes/transcribe", files=_audio())
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running" and response.json()["audio_id"]
    assert before - _balance(fresh) == 2
    ledger = fresh.get("/api/credits").json()["ledger"]
    assert ledger[0]["operation"] == "voice_note" and ledger[0]["units"] == 2 and ledger[0]["feature"] == "F1"


def test_a_failed_upload_costs_nothing(fresh, keyed):
    _consent(fresh)
    keyed.error = HTTPException(502, "Could not reach the MediBytes pipeline")
    before = _balance(fresh)
    response = fresh.post("/api/notes/transcribe", files=_audio())
    assert response.status_code == 502
    assert _balance(fresh) == before


def test_transcription_stops_with_402_when_credits_are_used_up(fresh, keyed):
    _consent(fresh)
    db = SessionLocal()
    try:
        credits._account(db).balance = 1
        db.commit()
    finally:
        db.close()
    response = fresh.post("/api/notes/transcribe", files=_audio())
    assert response.status_code == 402
    assert keyed.calls == 0, "the pipeline must not be called when the pack cannot pay for it"
    assert _balance(fresh) == 1
