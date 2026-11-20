"""FastAPI application: the HTTP face of the one pipeline.

    GET  /api/health                   pipeline name, gpt-4.1 readiness, job counts
    POST /api/jobs                     multipart `file` -> 202 {job_id, status, status_url}
    GET  /api/jobs                     recent jobs
    GET  /api/jobs/{id}                status, the seven stages, and the result when done
    GET  /api/jobs/{id}/files/{name}   input.*, cleaned.wav, discharge.json, entities.json, ...
    GET  /                             the integrated React UI (frontend/dist), when built

The hospital (HIMS) integration, behind `Authorization: Bearer <MEDIBYTES_API_KEYS>`:

    POST /api/v1/transcriptions                    multipart `file`, `audio_id`, `company_id`
    GET  /api/v1/transcriptions/{audio_id}         job + delivery state + the response string
    POST /api/v1/transcriptions/{audio_id}/redeliver

The UI routes above take no key, and they never list or serve a hospital upload.

Run:  python -m medibytes.api
"""
from __future__ import annotations

import hashlib
import hmac
import shutil
import tempfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import C1, Settings
from ..factory import build_pipeline
from ..pipeline import Pipeline
from .hims import AUDIO_ID_PATTERN, HimsDelivery
from .jobs import JobService
from .models import (
    Health,
    Job,
    JobAccepted,
    JobSummary,
    LlmHealth,
    TranscriptionAccepted,
    TranscriptionStatus,
)

AUDIO_EXT = {".wav", ".mp3", ".m4a", ".mp4", ".aac", ".flac", ".ogg", ".webm"}
CHUNK = 1024 * 1024


async def _save_upload(file: UploadFile, max_bytes: int) -> tuple[Path, str, str, str]:
    """Stream an upload to a temp file: (path, name, suffix, sha256). Raises the HTTP error
    for a wrong type, an empty file or one over `max_bytes`; the caller removes the file."""
    name = Path(file.filename or "upload").name
    suffix = Path(name).suffix.lower()
    if suffix not in AUDIO_EXT:
        raise HTTPException(415, f"unsupported file type {suffix or '(none)'}; "
                                 f"use one of {', '.join(sorted(AUDIO_EXT))}")
    digest, size = hashlib.sha256(), 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        while chunk := await file.read(CHUNK):
            size += len(chunk)
            if size > max_bytes:
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(413, f"file is larger than {max_bytes // (1024 * 1024)} MB")
            digest.update(chunk)
            tmp.write(chunk)
    if size == 0:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(400, "the uploaded file is empty")
    return tmp_path, name, suffix, digest.hexdigest()


def _lazy(build: Callable[[], Pipeline]) -> Callable[[], Pipeline]:
    """Build the pipeline on first use (models load on first transcription)."""
    cache: list[Pipeline] = []

    def get() -> Pipeline:
        if not cache:
            cache.append(build())
        return cache[0]
    return get


def create_app(settings: Settings | None = None,
               pipeline_provider: Callable[[], Pipeline] | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    jobs = JobService(settings.runs_dir,
                      pipeline_provider or _lazy(lambda: build_pipeline(settings)))
    hims = HimsDelivery(settings.runs_dir, jobs, url=settings.hims_url, token=settings.hims_token,
                        backoff_s=settings.hims_backoff_s, poll_s=settings.hims_poll_s)
    llm_configured = bool(settings.openai_api_key)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        hims.start()
        yield
        hims.stop()
        jobs.shutdown()

    app = FastAPI(title="MediBytes", version="1.0.0", lifespan=lifespan,
                  description=f"Dictation to discharge note. Pipeline: {C1.name}")
    app.state.jobs = jobs
    app.state.hims = hims
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health(pipeline=C1.name, llm=LlmHealth(model=C1.llm.model,
                                                      configured=llm_configured),
                      jobs=jobs.counts())

    @app.post("/api/jobs", response_model=JobAccepted, status_code=202)
    async def submit(file: Annotated[UploadFile, File()]) -> JobAccepted:
        if not llm_configured:
            raise HTTPException(503, "OPENAI_API_KEY is not set on the server; gpt-4.1 is "
                                     "part of the pipeline, so jobs cannot run without it")
        tmp_path, name, suffix, digest = await _save_upload(file, settings.max_upload_bytes)
        try:
            job = jobs.submit(digest, name, suffix, lambda dst: shutil.move(str(tmp_path), dst))
        finally:
            tmp_path.unlink(missing_ok=True)
        return JobAccepted(job_id=job["job_id"], status=job["status"],
                           status_url=f"/api/jobs/{job['job_id']}")

    @app.get("/api/jobs", response_model=list[JobSummary])
    def recent() -> list[dict]:
        return jobs.list()

    @app.get("/api/jobs/{job_id}", response_model=Job)
    def get_job(job_id: str) -> dict:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"no job {job_id}")
        return {**job, "result": jobs.result(job)}

    @app.get("/api/jobs/{job_id}/files/{name}")
    def get_file(job_id: str, name: str) -> FileResponse:
        path = jobs.file_path(job_id, name)
        if path is None:
            raise HTTPException(404, f"no file {name} for {job_id}")
        return FileResponse(path, filename=name)

    # ---- hospital (HIMS) integration: key-protected, separate from the open UI routes ----

    def require_key(authorization: Annotated[str | None, Header()] = None) -> None:
        if not settings.api_keys:
            raise HTTPException(503, "MEDIBYTES_API_KEYS is not set on the server; "
                                     "the integration API is closed until it is")
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not any(
                hmac.compare_digest(token.encode(), key.encode()) for key in settings.api_keys):
            raise HTTPException(401, "missing or wrong API key",
                                headers={"WWW-Authenticate": "Bearer"})

    def accepted(rec: dict) -> TranscriptionAccepted:
        job = jobs.get(rec["job_id"], include_private=True) or {"status": "failed"}
        return TranscriptionAccepted(
            audio_id=rec["audio_id"], company_id=rec["company_id"], job_id=rec["job_id"],
            status=job["status"], status_url=f"/api/v1/transcriptions/{rec['audio_id']}")

    @app.post("/api/v1/transcriptions", response_model=TranscriptionAccepted, status_code=202,
              dependencies=[Depends(require_key)])
    async def submit_transcription(
            file: Annotated[UploadFile, File()],
            audio_id: Annotated[str, Form(pattern=AUDIO_ID_PATTERN)],
            company_id: Annotated[int, Form()] = 1) -> TranscriptionAccepted:
        if not llm_configured:
            raise HTTPException(503, "OPENAI_API_KEY is not set on the server; gpt-4.1 is "
                                     "part of the pipeline, so jobs cannot run without it")
        existing = hims.get(audio_id)
        if existing and existing["state"] not in ("failed", "job_failed"):
            return accepted(existing)  # the same audio_id twice is one job
        tmp_path, name, suffix, digest = await _save_upload(file, settings.max_upload_bytes)
        try:  # a failed delivery sent again starts over, so a degraded run is not served from cache
            job = jobs.submit(digest, name, suffix, lambda dst: shutil.move(str(tmp_path), dst),
                              source="hims", rerun=existing is not None)
        finally:
            tmp_path.unlink(missing_ok=True)
        return accepted(hims.enqueue(audio_id, company_id, job["job_id"]))

    @app.get("/api/v1/transcriptions/{audio_id}", response_model=TranscriptionStatus,
             dependencies=[Depends(require_key)])
    def transcription_status(audio_id: str) -> dict:
        rec = hims.get(audio_id)
        if rec is None:
            raise HTTPException(404, f"no transcription for audio_id {audio_id}")
        job = jobs.get(rec["job_id"], include_private=True) or {"status": "failed",
                                                                 "error": "job record is missing"}
        return {"audio_id": rec["audio_id"], "company_id": rec["company_id"],
                "job_id": rec["job_id"], "job_status": job["status"], "job_error": job.get("error"),
                "delivery": hims.view(rec), "response": rec["response"],
                "needs_review": rec["needs_review"]}

    @app.post("/api/v1/transcriptions/{audio_id}/redeliver", status_code=202,
              response_model=TranscriptionAccepted, dependencies=[Depends(require_key)])
    def redeliver(audio_id: str) -> TranscriptionAccepted:
        try:
            rec = hims.redeliver(audio_id)
        except ValueError as exc:
            raise HTTPException(409, f"{exc}; only a failed delivery can be pushed again "
                                     f"(for a failed job, upload the recording again)") from None
        if rec is None:
            raise HTTPException(404, f"no transcription for audio_id {audio_id}")
        return accepted(rec)

    if (settings.web_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="frontend")

    return app
