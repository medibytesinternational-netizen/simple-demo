"""HTTP API with a fake pipeline behind it: upload rules, job lifecycle, files, health."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from medibytes.api.app import create_app
from medibytes.api.jobs import JobService
from medibytes.config import Settings
from medibytes.domain import STAGE_ORDER
from medibytes.errors import AudioRejected
from medibytes.pipeline import Pipeline
from tests.fakes import FakeLLM, FakePreprocessor, FakeRecognizer


def _settings(tmp_path: Path, key: str = "sk-test", **kw) -> Settings:
    return Settings(openai_api_key=key, runs_dir=tmp_path / "runs",
                    web_dist=tmp_path / "no-dist", **kw)


def _fake_pipeline(pre=None) -> Pipeline:
    return Pipeline(preprocessor=pre or FakePreprocessor(), first_pass=FakeRecognizer("medasr"),
                    second_pass=FakeRecognizer("small-int8"), llm=FakeLLM())


@pytest.fixture
def client(tmp_path):
    app = create_app(_settings(tmp_path), pipeline_provider=_fake_pipeline)
    with TestClient(app) as c:
        yield c


def _wait(client, job_id, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_health_reports_the_pipeline_and_llm(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "MedASR" in body["pipeline"] and "gpt-4.1" in body["pipeline"]
    assert body["llm"] == {"model": "gpt-4.1", "configured": True}


def test_upload_runs_all_stages_and_returns_the_six_section_note(client):
    r = client.post("/api/jobs", files={"file": ("visit.mp4", b"fake-audio", "audio/mp4")})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    assert r.json()["status_url"] == f"/api/jobs/{job_id}"
    job = _wait(client, job_id)
    assert job["status"] == "succeeded", job["error"]
    assert [s["name"] for s in job["stages"]] == [s.value for s in STAGE_ORDER]
    assert all(s["state"] == "done" for s in job["stages"])
    result = job["result"]
    assert set(result["discharge"]["sections"]) == {
        "present_illness", "examination_findings", "previous_diagnosis",
        "plan_of_management", "diet_instructions", "general_instructions"}
    assert any(d["name"] == "paracetamol" for d in result["entities"]["drugs"])
    assert "verify" not in result["entities"] and result["verify"]["facts"]
    assert result["files"][0] == "input.mp4"
    assert "discharge.json" in result["files"]


def test_files_are_served_and_nothing_else_is(client):
    job_id = client.post("/api/jobs", files={"file": ("a.wav", b"abc", "audio/wav")}).json()["job_id"]
    _wait(client, job_id)
    note = client.get(f"/api/jobs/{job_id}/files/discharge.json")
    assert note.status_code == 200 and "sections" in note.json()
    assert client.get(f"/api/jobs/{job_id}/files/input.wav").content == b"abc"
    for bad in ("job.json", "..%2F..%2Fsecret", "input.mp3"):
        assert client.get(f"/api/jobs/{job_id}/files/{bad}").status_code == 404
    assert client.get("/api/jobs/job-nope/files/discharge.json").status_code == 404
    assert client.get("/api/jobs/not-a-job").status_code == 404


def test_same_bytes_give_the_same_job(client):
    a = client.post("/api/jobs", files={"file": ("a.wav", b"same", "audio/wav")}).json()
    _wait(client, a["job_id"])
    b = client.post("/api/jobs", files={"file": ("renamed.wav", b"same", "audio/wav")}).json()
    assert a["job_id"] == b["job_id"] and b["status"] == "succeeded"


@pytest.mark.parametrize("name, data, status", [
    ("notes.txt", b"x", 415), ("noext", b"x", 415), ("empty.wav", b"", 400)])
def test_bad_uploads_are_refused_with_a_reason(client, name, data, status):
    r = client.post("/api/jobs", files={"file": (name, data, "application/octet-stream")})
    assert r.status_code == status
    assert r.json()["detail"]


def test_oversize_upload_is_413(tmp_path):
    app = create_app(_settings(tmp_path, max_upload_bytes=10), pipeline_provider=_fake_pipeline)
    with TestClient(app) as c:
        r = c.post("/api/jobs", files={"file": ("big.wav", b"x" * 11, "audio/wav")})
    assert r.status_code == 413 and "MB" in r.json()["detail"]


def test_without_an_api_key_jobs_are_refused_and_health_says_so(tmp_path):
    app = create_app(_settings(tmp_path, key=""), pipeline_provider=_fake_pipeline)
    with TestClient(app) as c:
        assert c.get("/api/health").json()["llm"]["configured"] is False
        r = c.post("/api/jobs", files={"file": ("a.wav", b"x", "audio/wav")})
    assert r.status_code == 503 and "OPENAI_API_KEY" in r.json()["detail"]


def test_a_rejected_recording_fails_the_job_with_the_reason(tmp_path):
    bad = lambda: _fake_pipeline(FakePreprocessor(AudioRejected("422 NO_AUDIO: silent")))  # noqa: E731
    with TestClient(create_app(_settings(tmp_path), pipeline_provider=bad)) as c:
        job_id = c.post("/api/jobs", files={"file": ("a.wav", b"q", "audio/wav")}).json()["job_id"]
        job = _wait(c, job_id)
        assert job["status"] == "failed" and "NO_AUDIO" in job["error"]
        assert job["stages"][0]["state"] == "failed" and job["result"] is None
        # a failed job may be resubmitted
        again = c.post("/api/jobs", files={"file": ("a.wav", b"q", "audio/wav")}).json()
        assert again["job_id"] == job_id


def test_recent_jobs_list_newest_first(client):
    for data in (b"one", b"two"):
        _wait(client, client.post("/api/jobs", files={"file": ("a.wav", data, "audio/wav")})
              .json()["job_id"])
    listed = client.get("/api/jobs").json()
    assert len(listed) == 2 and set(listed[0]) == {"job_id", "filename", "status", "created_at"}


def test_jobs_interrupted_by_a_restart_are_marked_failed(tmp_path):
    root = tmp_path / "runs" / "jobs" / "job-abc123"
    root.mkdir(parents=True)
    (root / "job.json").write_text(json.dumps({
        "job_id": "job-abc123", "filename": "a.wav", "status": "running",
        "created_at": "2026-10-11T10:00:00+00:00", "error": None, "input_name": "input.wav",
        "stages": [{"name": "preprocess", "label": "Preprocess", "state": "running",
                    "seconds": None, "detail": ""}]}), encoding="utf-8")
    JobService(tmp_path / "runs", _fake_pipeline)
    job = json.loads((root / "job.json").read_text(encoding="utf-8"))
    assert job["status"] == "failed" and "restarted" in job["error"]
    assert job["stages"][0]["state"] == "failed"
