"""Small registry for jobs that must run without anyone pressing a button.

A feature registers a function that takes a database session. ``main.lifespan`` runs every
registered job on its interval. Tests call ``run_jobs_once`` instead of waiting, and set
``MEDIBYTES_BACKGROUND=0`` so no timers start.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .db import SessionLocal

log = logging.getLogger("medibytes.background")


@dataclass(frozen=True)
class Job:
    name: str
    fn: Callable[[Session], object]
    interval_seconds: float


JOBS: dict[str, Job] = {}


def register(name: str, fn: Callable[[Session], object], interval_seconds: float = 60.0) -> None:
    JOBS[name] = Job(name, fn, interval_seconds)


def run_job(name: str) -> object:
    """Run one job now, in its own session. Commits on success, rolls back on error."""
    job = JOBS[name]
    db = SessionLocal()
    try:
        result = job.fn(db)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run_jobs_once() -> dict[str, object]:
    return {name: run_job(name) for name in list(JOBS)}


def enabled() -> bool:
    return os.getenv("MEDIBYTES_BACKGROUND", "1") != "0"


async def _loop(job: Job) -> None:
    while True:
        await asyncio.sleep(job.interval_seconds)
        try:
            await asyncio.to_thread(run_job, job.name)
        except Exception:  # a failing job must never stop the others
            log.exception("background job %s failed", job.name)


def start() -> list[asyncio.Task]:
    if not enabled():
        return []
    return [asyncio.create_task(_loop(job)) for job in JOBS.values()]


async def stop(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
