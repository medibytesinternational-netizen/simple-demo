"""HIMS integration: authenticated upload, the six-field note, and delivery to their receive API.

A local HTTP server stands in for himsapi.sriher.com. The one fact it copies from the
real service (probed 2026-10-22): a bad token answers HTTP 200 with
{"status":"Failed","Message":"Unauthorized"}, so failure is in the body, not the status.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from medibytes.api.app import create_app
from medibytes.api.hims import SECTIONS, format_response, needs_review
from medibytes.api.jobs import JobService
from medibytes.config import Settings
from medibytes.errors import AudioRejected, LLMUnavailable
from medibytes.pipeline import Pipeline
from tests.fakes import FakeLLM, FakePreprocessor, FakeRecognizer

KEY = "customer-key"
HIMS_TOKEN = "hims-token"
FAILED_BODY = (200, {"status": "Failed", "Message": "Unauthorized"})
OK_BODY = (200, {"status": "Success", "Message": "Saved"})
CLOUDFLARE = (403, "<html><title>Just a moment...</title></html>")


class Receiver:
    """Records every POST and answers from a script (the last reply repeats)."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"auth": self.headers.get("Authorization"),
                                       "type": self.headers.get("Content-Type"),
                                       "body": json.loads(body)})
                i = min(len(outer.requests), len(outer.replies)) - 1
                status, payload = outer.replies[i]
                data = payload if isinstance(payload, str) else json.dumps(payload)
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=UTF-8")
                self.end_headers()
                self.wfile.write(data.encode())

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/patinetcareop/audio_transcription_receive"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def receiver_factory():
    made = []

    def make(*replies):
        made.append(Receiver(replies))
        return made[-1]
    yield make
    for r in made:
        r.close()


def _fake_pipeline(pre=None) -> Pipeline:
    return Pipeline(preprocessor=pre or FakePreprocessor(), first_pass=FakeRecognizer("medasr"),
                    second_pass=FakeRecognizer("small-int8"), llm=FakeLLM())


def _settings(tmp_path: Path, **kw) -> Settings:
    base = dict(openai_api_key="sk-test", runs_dir=tmp_path / "runs", web_dist=tmp_path / "no-dist",
                api_keys=(KEY,), hims_token=HIMS_TOKEN, hims_backoff_s=(0, 0), hims_poll_s=3600)
    return Settings(**{**base, **kw})


def _app_client(tmp_path, url="", pipeline=_fake_pipeline, **kw):
    app = create_app(_settings(tmp_path, hims_url=url, **kw), pipeline_provider=pipeline)
    return TestClient(app)


AUTH = {"Authorization": f"Bearer {KEY}"}


def _send(c, audio_id="aud-1", data=b"audio-bytes", company_id=None, headers=AUTH):
    form = {"audio_id": audio_id}
    if company_id is not None:
        form["company_id"] = str(company_id)
    return c.post("/api/v1/transcriptions", data=form, headers=headers,
                  files={"file": ("visit.wav", data, "audio/wav")})


def _wait_job(c, audio_id):
    end = time.time() + 10
    while time.time() < end:
        body = c.get(f"/api/v1/transcriptions/{audio_id}", headers=AUTH).json()
        if body["job_status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _deliver(c, audio_id):
    """Wait for the job, run one delivery pass, return the status."""
    _wait_job(c, audio_id)
    c.app.state.hims.tick()
    return c.get(f"/api/v1/transcriptions/{audio_id}", headers=AUTH).json()


# ---- the formatter -------------------------------------------------------------------


def _note(**sections):
    return {"sections": {k: {"items": [{"text": t, "source_sentence": t} for t in sections.get(k, [])]}
                         for k in SECTIONS}, "provenance": {"schema": "valid"}}


def test_response_is_a_string_holding_one_object_with_six_string_fields():
    out = format_response(_note(present_illness=["fever", "cough"], plan_of_management=["CBC"]))
    assert isinstance(out, str)
    rows = json.loads(out)
    assert len(rows) == 1 and list(rows[0]) == list(SECTIONS)
    assert all(isinstance(v, str) for v in rows[0].values())
    assert rows[0]["present_illness"] == "fever; cough" and rows[0]["plan_of_management"] == "CBC"
    assert rows[0]["diet_instructions"] == ""


def test_an_item_repeated_inside_a_longer_one_is_dropped():
    row = json.loads(format_response(_note(
        present_illness=["fever", "three days of fever", "cough", "productive cough", "fever"])))[0]
    assert row["present_illness"] == "three days of fever; productive cough"


def test_an_affirmed_finding_is_not_swallowed_by_a_longer_negated_one():
    row = json.loads(format_response(_note(
        present_illness=["chest pain", "no radiation of chest pain", "rice", "price list"])))[0]
    assert row["present_illness"].split("; ") == [
        "chest pain", "no radiation of chest pain", "rice", "price list"]


def test_denied_prefix_survives():
    row = json.loads(format_response(_note(general_instructions=["DENIED allergy: penicillin"])))[0]
    assert row["general_instructions"] == "DENIED allergy: penicillin"


def _row(section, *texts):
    return json.loads(format_response(_note(**{section: list(texts)})))[0][section]


def test_a_denied_symptom_reads_as_a_denial():
    assert _row("present_illness", "DENIED: fever", "DENIED: chest pain", "cough") == (
        "Denies fever; Denies chest pain; cough")


def test_a_denial_and_the_same_symptom_present_are_both_kept():
    assert _row("present_illness", "fever", "DENIED: fever") == "fever; Denies fever"


def test_the_no_dose_label_is_not_sent():
    assert _row("plan_of_management", "budesonide no dose", "paracetamol 650 mg",
                "NOT GIVEN: ibuprofen no dose") == (
        "budesonide; paracetamol 650 mg; NOT GIVEN: ibuprofen")


def test_albuterol_is_sent_by_its_international_name():
    assert _row("plan_of_management", "albuterol no dose", "prednisolone 40 mg") == (
        "salbutamol; prednisolone 40 mg")
    assert _row("plan_of_management", "Albuterol 2.5 mg") == "Salbutamol 2.5 mg"
    # the same drug heard twice, once without a dose: the dosed one is the complete item
    assert _row("plan_of_management", "albuterol no dose", "Albuterol 2.5 mg") == "Salbutamol 2.5 mg"


def test_two_readings_of_one_vital_keep_the_one_that_has_a_unit():
    # heard "pulse 100, 104 beats per minute": the second is the complete reading
    assert _row("examination_findings", "pulse 100", "pulse 104 beats per minute",
                "blood pressure 112/70") == "pulse 104 beats per minute; blood pressure 112/70"


@pytest.mark.parametrize("heard, sent", [
    ("Pulse 100 104 beats per minute", "Pulse 104 beats per minute"),
    ("pulse 100, 104 beats per minute", "pulse 104 beats per minute"),
    ("respiratory rate 24 26 breaths per minute", "respiratory rate 26 breaths per minute"),
    ("blood pressure 112/70", "blood pressure 112/70"),
    ("temperature 99 degrees Fahrenheit", "temperature 99 degrees Fahrenheit"),
    ("93% on room air", "93% on room air"),
    ("pulse 104 beats per minute", "pulse 104 beats per minute"),
])
def test_one_vital_item_holding_two_numbers_keeps_the_last(heard, sent):
    # "pulse 100, 104 beats per minute" is a restart: a pulse cannot have two values
    assert _row("examination_findings", heard) == sent


def test_two_readings_with_nothing_to_choose_by_are_both_kept():
    assert _row("examination_findings", "pulse 100", "pulse 104") == "pulse 100; pulse 104"
    assert _row("examination_findings", "pulse 100 beats per minute",
                "pulse 104 beats per minute") == "pulse 100 beats per minute; pulse 104 beats per minute"


def test_different_vitals_are_never_treated_as_conflicts():
    assert _row("examination_findings", "pulse 90", "respiratory rate 22") == (
        "pulse 90; respiratory rate 22")


def test_a_note_the_llm_never_wrote_is_never_formatted():
    skipped = {**_note(), "provenance": {
        "schema": "valid", "llm_engine": "discharge-skipped (LLMUnavailable: OpenAI refused the API key)"}}
    with pytest.raises(ValueError, match="not written"):
        format_response(skipped)


def test_a_note_that_failed_its_schema_is_never_formatted():
    bad = {**_note(present_illness=["fever"]), "provenance": {"schema": "INVALID", "schema_error": "x"}}
    with pytest.raises(ValueError, match="schema"):
        format_response(bad)


# ---- inbound auth ------------------------------------------------------------------


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}, {"Authorization": KEY},
                                     {"Authorization": f"Basic {KEY}"}])
def test_v1_needs_the_customer_key(tmp_path, headers):
    with _app_client(tmp_path) as c:
        r = _send(c, headers=headers)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
        assert c.get("/api/v1/transcriptions/aud-1", headers=headers).status_code == 401
        assert c.post("/api/v1/transcriptions/aud-1/redeliver", headers=headers).status_code == 401


def test_v1_is_closed_when_no_key_is_configured(tmp_path):
    with _app_client(tmp_path, api_keys=()) as c:
        assert _send(c).status_code == 503
        assert _send(c, headers={}).status_code == 503


@pytest.mark.parametrize("bad", ["", "a b", "x" * 65, "../etc", "a/b"])
def test_audio_id_is_restricted(tmp_path, bad):
    with _app_client(tmp_path) as c:
        assert _send(c, audio_id=bad).status_code == 422


def test_uuid_audio_ids_from_the_hospital_are_accepted(tmp_path):
    with _app_client(tmp_path) as c:
        r = _send(c, audio_id="42ce7530-e963-456e-a72d-0a9d4cffbfb0")
        assert r.status_code == 202 and r.json()["company_id"] == 1


def test_v1_upload_has_the_same_file_rules_as_the_ui(tmp_path):
    with _app_client(tmp_path, max_upload_bytes=10) as c:
        assert c.post("/api/v1/transcriptions", data={"audio_id": "a"}, headers=AUTH,
                      files={"file": ("n.txt", b"x", "text/plain")}).status_code == 415
        assert _send(c, data=b"x" * 11).status_code == 413
        assert _send(c, data=b"").status_code == 400


# ---- the UI stays open and does not see patient data ---------------------------------


def test_the_ui_api_needs_no_key_and_does_not_list_hims_jobs(tmp_path):
    with _app_client(tmp_path) as c:
        sent = _send(c, audio_id="aud-patient", data=b"patient").json()
        _wait_job(c, "aud-patient")
        ui = c.post("/api/jobs", files={"file": ("demo.wav", b"demo", "audio/wav")}).json()
        end = time.time() + 10
        while c.get(f"/api/jobs/{ui['job_id']}").json()["status"] not in ("succeeded", "failed"):
            assert time.time() < end
            time.sleep(0.05)
        listed = [j["job_id"] for j in c.get("/api/jobs").json()]
        assert listed == [ui["job_id"]]
        assert c.get("/api/health").json()["jobs"] == {"succeeded": 1}
        hidden = sent["job_id"]
        assert c.get(f"/api/jobs/{hidden}").status_code == 404
        assert c.get(f"/api/jobs/{hidden}/files/discharge.json").status_code == 404
        assert c.get(f"/api/jobs/{hidden}/files/input.wav").status_code == 404
        # the authenticated route still serves the status
        assert c.get("/api/v1/transcriptions/aud-patient", headers=AUTH).status_code == 200


# ---- delivery -------------------------------------------------------------------------


def test_the_note_is_pushed_in_the_hospitals_shape(tmp_path, receiver_factory):
    rx = receiver_factory(OK_BODY)
    with _app_client(tmp_path, rx.url) as c:
        _send(c, audio_id="42ce7530-e963-456e-a72d-0a9d4cffbfb0", company_id=7)
        st = _deliver(c, "42ce7530-e963-456e-a72d-0a9d4cffbfb0")
    assert st["delivery"]["state"] == "delivered" and st["delivery"]["attempts"] == 1
    [req] = rx.requests
    assert req["auth"] == f"Bearer {HIMS_TOKEN}" and req["type"] == "application/json"
    assert set(req["body"]) == {"audio_id", "company_id", "response"}
    assert req["body"]["audio_id"] == "42ce7530-e963-456e-a72d-0a9d4cffbfb0"
    assert req["body"]["company_id"] == 7
    [row] = json.loads(req["body"]["response"])
    note = json.loads((tmp_path / "runs" / "jobs" / st["job_id"] / "discharge.json").read_text())
    assert list(row) == list(SECTIONS)
    assert "fever" in row["present_illness"] and "cough" in row["present_illness"]
    assert req["body"]["response"] == format_response(note)  # what the UI's note says, as strings
    assert st["response"] == req["body"]["response"]


def test_a_bad_token_answered_200_with_a_failed_body_is_not_delivered(tmp_path, receiver_factory):
    rx = receiver_factory(FAILED_BODY)
    with _app_client(tmp_path, rx.url) as c:
        _send(c)
        st = _deliver(c, "aud-1")
        c.app.state.hims.tick()
    assert st["delivery"]["state"] == "failed" and "Unauthorized" in st["delivery"]["last_error"]
    assert st["delivery"]["last_http_status"] == 200
    assert len(rx.requests) == 1  # a refused token is not retried


def test_server_errors_are_retried_then_delivered(tmp_path, receiver_factory):
    rx = receiver_factory((500, "oops"), OK_BODY)
    with _app_client(tmp_path, rx.url) as c:
        _send(c)
        st = _deliver(c, "aud-1")
        assert st["delivery"]["state"] == "pending" and st["delivery"]["attempts"] == 1
        c.app.state.hims.tick()
        st = c.get("/api/v1/transcriptions/aud-1", headers=AUTH).json()
    assert st["delivery"]["state"] == "delivered" and st["delivery"]["attempts"] == 2


def test_retries_stop_after_the_backoff_schedule(tmp_path, receiver_factory):
    rx = receiver_factory((503, "down"))
    with _app_client(tmp_path, rx.url) as c:
        _send(c)
        _wait_job(c, "aud-1")
        for _ in range(6):
            c.app.state.hims.tick()
        st = c.get("/api/v1/transcriptions/aud-1", headers=AUTH).json()
    assert st["delivery"]["state"] == "failed" and len(rx.requests) == 3  # 1 + two retries


def test_a_cloudflare_challenge_is_named_and_not_retried(tmp_path, receiver_factory):
    rx = receiver_factory(CLOUDFLARE)
    with _app_client(tmp_path, rx.url) as c:
        _send(c)
        st = _deliver(c, "aud-1")
        c.app.state.hims.tick()
    assert st["delivery"]["state"] == "failed" and "Cloudflare" in st["delivery"]["last_error"]
    assert len(rx.requests) == 1


def test_a_connection_error_is_retried(tmp_path):
    with _app_client(tmp_path, "http://127.0.0.1:9/never") as c:
        _send(c)
        st = _deliver(c, "aud-1")
    assert st["delivery"]["state"] == "pending" and st["delivery"]["last_error"]


def test_deliveries_wait_while_hims_is_not_configured(tmp_path):
    with _app_client(tmp_path, "") as c:
        _send(c)
        st = _deliver(c, "aud-1")
    assert st["delivery"]["state"] == "pending" and "MEDIBYTES_HIMS_URL" in st["delivery"]["last_error"]


def test_redeliver_after_a_failed_push(tmp_path, receiver_factory):
    rx = receiver_factory(FAILED_BODY, OK_BODY)
    with _app_client(tmp_path, rx.url) as c:
        _send(c)
        assert _deliver(c, "aud-1")["delivery"]["state"] == "failed"
        assert c.post("/api/v1/transcriptions/aud-1/redeliver", headers=AUTH).status_code == 202
        c.app.state.hims.tick()
        st = c.get("/api/v1/transcriptions/aud-1", headers=AUTH).json()
        assert st["delivery"]["state"] == "delivered" and len(rx.requests) == 2
        assert c.post("/api/v1/transcriptions/aud-1/redeliver", headers=AUTH).status_code == 409
        assert c.post("/api/v1/transcriptions/nope/redeliver", headers=AUTH).status_code == 404


def test_a_failed_recording_sends_nothing(tmp_path, receiver_factory):
    rx = receiver_factory(OK_BODY)
    bad = lambda: _fake_pipeline(FakePreprocessor(AudioRejected("422 NO_AUDIO: silent")))  # noqa: E731
    with _app_client(tmp_path, rx.url, pipeline=bad) as c:
        _send(c)
        st = _deliver(c, "aud-1")
    assert st["delivery"]["state"] == "job_failed" and "NO_AUDIO" in st["delivery"]["last_error"]
    assert rx.requests == [] and st["response"] is None


def test_a_blank_note_from_a_broken_llm_is_not_delivered_and_a_reupload_reruns_it(
        tmp_path, receiver_factory):
    rx = receiver_factory(OK_BODY)
    broken = [True]

    def pipeline():
        llm = FakeLLM(error=LLMUnavailable("OpenAI refused the API key (HTTP 401)")) if broken[0] \
            else FakeLLM()
        return Pipeline(preprocessor=FakePreprocessor(), first_pass=FakeRecognizer("medasr"),
                        second_pass=FakeRecognizer("small-int8"), llm=llm)

    with _app_client(tmp_path, rx.url, pipeline=pipeline) as c:
        first = _send(c).json()
        st = _deliver(c, "aud-1")
        assert st["job_status"] == "succeeded"  # the pipeline degrades, it does not fail
        assert st["delivery"]["state"] == "failed" and "not written" in st["delivery"]["last_error"]
        assert rx.requests == [] and st["response"] is None
        broken[0] = False  # the key is fixed; the hospital uploads the recording again
        again = _send(c).json()
        assert again["job_id"] == first["job_id"]
        st = _deliver(c, "aud-1")
    assert st["delivery"]["state"] == "delivered" and len(rx.requests) == 1
    assert "fever" in json.loads(rx.requests[0]["body"]["response"])[0]["present_illness"]


def test_the_same_audio_id_is_idempotent_and_sends_once(tmp_path, receiver_factory):
    rx = receiver_factory(OK_BODY)
    with _app_client(tmp_path, rx.url) as c:
        first = _send(c).json()
        _deliver(c, "aud-1")
        again = _send(c, data=b"other bytes").json()
        c.app.state.hims.tick()
        assert again["job_id"] == first["job_id"] and len(rx.requests) == 1


def test_one_recording_under_two_audio_ids_gives_two_deliveries(tmp_path, receiver_factory):
    rx = receiver_factory(OK_BODY)
    with _app_client(tmp_path, rx.url) as c:
        a = _send(c, audio_id="aud-a", data=b"same").json()
        b = _send(c, audio_id="aud-b", data=b"same").json()
        _wait_job(c, "aud-a")
        c.app.state.hims.tick()
    assert a["job_id"] == b["job_id"]
    assert sorted(r["body"]["audio_id"] for r in rx.requests) == ["aud-a", "aud-b"]


def test_the_background_worker_delivers_without_a_manual_pass(tmp_path, receiver_factory):
    rx = receiver_factory(OK_BODY)
    with _app_client(tmp_path, rx.url, hims_poll_s=0.05) as c:
        _send(c)
        end = time.time() + 10
        while not rx.requests:
            assert time.time() < end, "worker never delivered"
            time.sleep(0.05)
        time.sleep(0.2)
        assert c.get("/api/v1/transcriptions/aud-1", headers=AUTH).json()["delivery"]["state"] == "delivered"


def test_needs_review_items_are_listed_because_the_plain_string_cannot_flag_them():
    note = _note(plan_of_management=["Complete blood count", "paracetamol 650 mg"])
    note["sections"]["plan_of_management"]["items"][0]["verified_status"] = "needs_review"
    note["sections"]["plan_of_management"]["items"][1]["verified_status"] = "verified"
    assert needs_review(note) == [{"section": "plan_of_management", "text": "Complete blood count"}]
    assert json.loads(format_response(note))[0]["plan_of_management"] == (
        "Complete blood count; paracetamol 650 mg")  # still sent


# ---- restarts ---------------------------------------------------------------------------


def test_a_hims_job_cut_off_by_a_restart_is_run_again(tmp_path):
    root = tmp_path / "runs" / "jobs" / "job-abc123"
    root.mkdir(parents=True)
    (root / "input.wav").write_bytes(b"audio")
    (root / "job.json").write_text(json.dumps({
        "job_id": "job-abc123", "filename": "a.wav", "status": "running", "source": "hims",
        "created_at": "2026-10-11T10:00:00+00:00", "error": None, "input_name": "input.wav",
        "input_sha256": "a" * 64,
        "stages": [{"name": "preprocess", "label": "Preprocess", "state": "running",
                    "seconds": None, "detail": ""}]}), encoding="utf-8")
    ui = tmp_path / "runs" / "jobs" / "job-def456"
    ui.mkdir(parents=True)
    ui_job = {**json.loads((root / "job.json").read_text()), "job_id": "job-def456"}
    ui_job.pop("source")
    (ui / "job.json").write_text(json.dumps(ui_job), encoding="utf-8")

    jobs = JobService(tmp_path / "runs", _fake_pipeline)
    end = time.time() + 10
    while jobs.get("job-abc123", include_private=True)["status"] != "succeeded":
        assert time.time() < end, "the hims job was not re-run"
        time.sleep(0.05)
    assert jobs.get("job-def456")["status"] == "failed"  # the UI's behaviour is unchanged
    jobs.shutdown()
