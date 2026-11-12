"""Job queue: one worker runs the pipeline; every job's state lives on disk.

    <runs>/jobs/<job_id>/input.<ext>      the upload
    <runs>/jobs/<job_id>/job.json         status, stages, error (rewritten on every event)
    <runs>/jobs/<job_id>/*.json, report.md, cleaned.wav   the pipeline's outputs

One worker because the speech models are large and loaded once. The job id is a
hash of the uploaded bytes, so the same recording is never processed twice
unless the earlier attempt failed. On startup, a job left queued or running by a
previous process is marked failed rather than silently lost.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..domain import STAGE_LABELS, STAGE_ORDER, StageEvent, StageState
from ..output import FILES, write_result
from ..pipeline import Pipeline

INPUT_PREFIX = "input"
SERVABLE = frozenset(FILES) | {"cleaned.wav"}


def job_id_for(data_hash: str) -> str:
    return f"job-{data_hash[:16]}"


class JobService:
    def __init__(self, runs_dir: Path, pipeline_provider: Callable[[], Pipeline]):
        self.root = Path(runs_dir) / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self._pipeline_provider = pipeline_provider
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline")
        # One lock for every job.json read and write: on Windows an atomic replace
        # fails while another thread has the file open, so access is serialised.
        self._lock = threading.RLock()
        self._recover()

    # ---- persistence -------------------------------------------------------

    def _dir(self, job_id: str) -> Path:
        return self.root / job_id

    def _read(self, job_id: str) -> dict[str, Any] | None:
        path = self._dir(job_id) / "job.json"
        with self._lock:
            if not path.is_file():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, job: dict[str, Any]) -> None:
        path = self._dir(job["job_id"]) / "job.json"
        tmp = path.with_suffix(".tmp")
        with self._lock:
            tmp.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)  # atomic: a reader never sees half a file

    def _all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [json.loads(p.read_text(encoding="utf-8")) for p in self.root.glob("*/job.json")]

    def _recover(self) -> None:
        for path in self.root.glob("*/job.json"):
            job = json.loads(path.read_text(encoding="utf-8"))
            if job["status"] in ("queued", "running"):
                if _is_private(job) and (path.parent / job["input_name"]).is_file():
                    # A hospital upload cannot be re-sent by the hospital (their API has no
                    # failure channel), so a restart must not lose it: run it again.
                    job["status"], job["error"] = "queued", None
                    for stage in job["stages"]:
                        stage.update(state="pending", seconds=None, detail="")
                    self._write(job)
                    self._executor.submit(self._run_safely, job["job_id"])
                    continue
                job["status"] = "failed"
                job["error"] = "the server restarted before this job finished; submit it again"
                for stage in job["stages"]:
                    if stage["state"] in ("pending", "running"):
                        stage["state"] = "failed" if stage["state"] == "running" else "pending"
                self._write(job)

    # ---- queries -----------------------------------------------------------

    def get(self, job_id: str, include_private: bool = False) -> dict[str, Any] | None:
        """A job by id. Hospital uploads are private: only the authenticated routes ask for them."""
        if not _safe_id(job_id):
            return None
        job = self._read(job_id)
        if job is not None and _is_private(job) and not include_private:
            return None
        return job

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        jobs = [j for j in self._all() if not _is_private(j)]
        jobs.sort(key=lambda j: j["created_at"], reverse=True)
        return [{k: j[k] for k in ("job_id", "filename", "status", "created_at")}
                for j in jobs[:limit]]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for job in self._all():
            if not _is_private(job):
                out[job["status"]] = out.get(job["status"], 0) + 1
        return out

    def file_path(self, job_id: str, name: str, include_private: bool = False) -> Path | None:
        """A servable output or the original upload; None for anything else."""
        job = self.get(job_id, include_private)
        if job is None:
            return None
        if name not in SERVABLE and name != job.get("input_name"):
            return None
        path = self._dir(job_id) / name
        return path if path.is_file() else None

    def result(self, job: dict[str, Any]) -> dict[str, Any] | None:
        if job["status"] != "succeeded":
            return None
        d = self._dir(job["job_id"])

        def load(name: str) -> dict[str, Any]:
            return json.loads((d / name).read_text(encoding="utf-8"))

        meta = load("clean_meta.json")
        entities = load("entities.json")
        return {
            "audio": {k: meta.get(k) for k in ("duration_s", "sample_rate", "vad_ratio", "snr_db",
                                              "rms_dbfs_before", "rms_dbfs_after",
                                              "input_sha256")},
            "transcript": load("transcript.json"),
            "entities": {k: v for k, v in entities.items() if k not in ("verify", "discharge")},
            "verify": load("verify.json"),
            "discharge": load("discharge.json"),
            "files": [job["input_name"], *(n for n in ("cleaned.wav", *FILES)
                                           if (d / n).is_file())],
        }

    # ---- submission --------------------------------------------------------

    def submit(self, data_hash: str, filename: str, suffix: str,
               write_input: Callable[[Path], None], source: str | None = None,
               rerun: bool = False) -> dict[str, Any]:
        """Queue a job for an upload (or return the existing one). Idempotent.

        `source="hims"` marks a hospital upload: it is left out of the open job list and
        file routes. A recording the UI already holds keeps its (public) job. `rerun` runs
        the recording again even though a finished job exists (the hospital re-sending
        after a degraded run).
        """
        job_id = job_id_for(data_hash)
        with self._lock:
            existing = self._read(job_id)
            if existing and existing["status"] != "failed" and not rerun:
                return existing
            d = self._dir(job_id)
            d.mkdir(parents=True, exist_ok=True)
            input_name = f"{INPUT_PREFIX}{suffix}"
            write_input(d / input_name)
            job = {"job_id": job_id, "filename": filename, "status": "queued",
                   "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                   "error": None, "input_name": input_name, "input_sha256": data_hash,
                   "stages": [{"name": s.value, "label": STAGE_LABELS[s], "state": "pending",
                               "seconds": None, "detail": ""} for s in STAGE_ORDER]}
            if source:
                job["source"] = source
            self._write(job)
        self._executor.submit(self._run_safely, job_id)
        return job

    def _run_safely(self, job_id: str) -> None:
        """A worker thread that dies silently leaves a job "running" forever."""
        try:
            self._run(job_id)
        except Exception as exc:  # pragma: no cover - last-resort bookkeeping
            job = self._read(job_id) or {}
            if job:
                job.update(status="failed", error=f"internal error: {type(exc).__name__}: {exc}")
                self._write(job)

    def _run(self, job_id: str) -> None:
        job = self._read(job_id)
        assert job is not None
        job["status"] = "running"
        self._write(job)

        def on_event(event: StageEvent) -> None:
            for stage in job["stages"]:
                if stage["name"] == event.stage.value:
                    stage.update(state=event.state.value, seconds=event.seconds,
                                 detail=event.detail)
            self._write(job)

        d = self._dir(job_id)
        try:
            pipeline = self._pipeline_provider()
            result = pipeline.run(d / job["input_name"], d, job_id=job_id, sink=on_event)
            write_result(result, d, job["filename"])
            job["status"] = "succeeded"
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = f"{type(exc).__name__}: {exc}"[:500]
            for stage in job["stages"]:
                if stage["state"] == StageState.RUNNING.value:
                    stage["state"] = StageState.FAILED.value
        self._write(job)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def _is_private(job: dict[str, Any]) -> bool:
    return job.get("source") == "hims"


def _safe_id(job_id: str) -> bool:
    return job_id.startswith("job-") and job_id[4:].isalnum() and len(job_id) <= 40
