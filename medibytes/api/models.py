"""Response models. They mirror `frontend/src/medibytes/api/types.ts`; keep the two in step.

Chart rows, verify facts and the discharge note travel as the JSON the pipeline
writes (`schemas/*.schema.json`), so they are typed as objects here.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

JobStatus = Literal["queued", "running", "succeeded", "failed"]
StageStateName = Literal["pending", "running", "done", "degraded", "failed"]


class StageStatus(BaseModel):
    name: str
    label: str
    state: StageStateName
    seconds: float | None = None
    detail: str = ""


class JobSummary(BaseModel):
    job_id: str
    filename: str
    status: JobStatus
    created_at: str


class AudioMeta(BaseModel):
    duration_s: float
    sample_rate: int
    vad_ratio: float | None = None
    snr_db: float | None = None
    rms_dbfs_before: float | None = None
    rms_dbfs_after: float | None = None
    input_sha256: str


class JobResult(BaseModel):
    audio: AudioMeta
    transcript: dict[str, Any]
    entities: dict[str, Any]
    verify: dict[str, Any]
    discharge: dict[str, Any]
    files: list[str]


class Job(JobSummary):
    error: str | None = None
    stages: list[StageStatus]
    result: JobResult | None = None


class JobAccepted(BaseModel):
    job_id: str
    status: JobStatus
    status_url: str


class TranscriptionAccepted(BaseModel):
    audio_id: str
    company_id: int
    job_id: str
    status: JobStatus
    status_url: str


class Delivery(BaseModel):
    state: Literal["pending", "delivered", "failed", "job_failed"]
    attempts: int
    last_http_status: int | None = None
    last_error: str | None = None
    hims_reply: str | None = None
    delivered_at: str | None = None
    next_attempt_at: str | None = None


class TranscriptionStatus(BaseModel):
    audio_id: str
    company_id: int
    job_id: str
    job_status: JobStatus
    job_error: str | None = None
    delivery: Delivery
    response: str | None = None  # exactly what was (or will be) sent as `response`
    needs_review: list[dict[str, str]] = []


class LlmHealth(BaseModel):
    model: str
    configured: bool


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    pipeline: str
    llm: LlmHealth
    jobs: dict[str, int]
