"""OPD voice notes through the local MediBytes pipeline (the repo's ``medibytes/`` package).

The recording is queued on ``medibytes.api.jobs.JobService`` (one worker thread, job state on
disk) and the six-section discharge note it produces is mapped onto the F1 consult draft.
The pipeline's own output format is unchanged; ``_note_from_discharge`` flattens it here.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..config import settings

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SECTIONS = [
    "present_illness",
    "examination_findings",
    "previous_diagnosis",
    "plan_of_management",
    "diet_instructions",
    "general_instructions",
]
SECTION_LABELS = {
    "present_illness": "Present illness",
    "examination_findings": "Examination findings",
    "previous_diagnosis": "Diagnosis",
    "plan_of_management": "Plan of management",
    "diet_instructions": "Diet instructions",
    "general_instructions": "General instructions",
}

_lock = threading.Lock()
_service: Any = None


def configured() -> bool:
    """The MediBytes pipeline needs gpt-4.1, so it runs only with an OpenAI key."""
    return bool(settings.openai_api_key)


def _jobs() -> Any:
    """Start the job service once; the speech models load on the first job, not at import."""
    global _service
    with _lock:
        if _service is None:
            try:
                from medibytes.api.jobs import JobService
                from medibytes.config import Settings
                from medibytes.factory import build_pipeline
            except ImportError as exc:
                raise HTTPException(
                    503, f"The MediBytes pipeline is not installed ({exc.name}); install requirements-medibytes.txt"
                ) from exc
            pipeline_lock = threading.Lock()
            built: dict[str, Any] = {}

            def provider() -> Any:
                with pipeline_lock:
                    if "p" not in built:
                        built["p"] = build_pipeline(Settings.from_env(env_file=None))
                    return built["p"]

            _service = JobService(settings.medibytes_runs_dir, provider)
        return _service


def _index(audio_id: str) -> Path:
    return Path(settings.medibytes_runs_dir) / "audio" / f"{audio_id}.json"


def submit(contents: bytes, filename: str, content_type: str, audio_id: str) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower() or ".webm"
    data_hash = hashlib.sha256(contents).hexdigest()
    job = _jobs().submit(data_hash, filename, suffix, lambda path: path.write_bytes(contents))
    index = _index(audio_id)
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({"job_id": job["job_id"]}), encoding="utf-8")
    return {"audio_id": audio_id, "job_id": job["job_id"], "status": job["status"]}


def fetch(audio_id: str) -> dict[str, Any] | None:
    index = _index(audio_id)
    if not index.is_file():
        return None
    service = _jobs()
    job = service.get(json.loads(index.read_text(encoding="utf-8"))["job_id"])
    if job is None:
        return None
    out: dict[str, Any] = {"audio_id": audio_id, "job_status": job["status"], "job_error": job.get("error")}
    if job["status"] == "succeeded":
        discharge = (service.result(job) or {}).get("discharge") or {}
        note, needs_review = _note_from_discharge(discharge)
        out.update(response=json.dumps([note]), needs_review=needs_review)
    return out


def _note_from_discharge(discharge: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, str]]]:
    """medibytes ``discharge.json`` (sections -> items) -> one string per section plus review flags."""
    sections = discharge.get("sections") or {}
    note: dict[str, str] = {}
    needs_review: list[dict[str, str]] = []
    for key in SECTIONS:
        items = (sections.get(key) or {}).get("items") or []
        texts = [str(item.get("text") or "").strip() for item in items]
        note[key] = "; ".join(t for t in texts if t)
        needs_review += [
            {"section": key, "text": str(item.get("text") or "")}
            for item in items
            if item.get("verified_status") == "needs_review"
        ]
    return note, needs_review


def parse_note(response: str | None) -> dict[str, str]:
    """`response` is a JSON string holding a one-object array."""
    try:
        note = json.loads(response or "")[0]
    except (ValueError, IndexError, TypeError, KeyError) as exc:
        raise HTTPException(502, "The pipeline returned an unreadable note") from exc
    return {key: str(note.get(key) or "").strip() for key in SECTIONS}


def note_to_transcript(note: dict[str, str]) -> str:
    """One line per dictated section, so each section becomes one citable transcript segment."""
    return "\n".join(f"{SECTION_LABELS[key]}: {note[key]}" for key in SECTIONS if note[key])


def to_f1_content(note: dict[str, str], needs_review: list[dict[str, Any]], event_id: str) -> dict[str, Any]:
    """Map the six pipeline sections onto the F1 consult draft shape.

    Segment ids follow note_to_transcript's line order (seg_1, seg_2, ...).
    """
    segment_of: dict[str, str] = {}
    index = 0
    for key in SECTIONS:
        if note[key]:
            index += 1
            segment_of[key] = f"seg_{index}"

    def claim(text: str, key: str) -> dict[str, Any]:
        return {
            "text": text,
            "source_event_ids": [event_id],
            "source_segment_ids": [segment_of[key]],
            "confidence": 0.7,
        }

    def section(key: str) -> dict[str, Any] | None:
        return claim(note[key], key) if note[key] else None

    def items(key: str, sep: str = ";") -> list[dict[str, Any]]:
        if not note[key]:
            return []
        return [claim(part.strip(), key) for part in note[key].split(sep) if part.strip()]

    follow_up_parts = [note[k] for k in ("diet_instructions", "general_instructions") if note[k]]
    follow_up = None
    if follow_up_parts:
        follow_up = {
            "text": " ".join(follow_up_parts),
            "source_event_ids": [event_id],
            "source_segment_ids": [segment_of[k] for k in ("diet_instructions", "general_instructions") if note[k]],
            "confidence": 0.7,
        }

    hpi = section("present_illness")
    chief = None
    if note["present_illness"]:
        first = note["present_illness"].split(".")[0].strip()
        chief = claim(first, "present_illness") if first else None

    not_documented = [SECTION_LABELS[key] for key in SECTIONS if not note[key]]

    return {
        "chief_complaint": chief,
        "hpi": hpi,
        "exam": {"general": section("examination_findings"), "systemic": None},
        "assessment": items("previous_diagnosis"),
        "plan": items("plan_of_management"),
        "medication_mentions": [],
        "follow_up": follow_up,
        "not_documented": not_documented,
        "needs_review": [
            {"section": SECTION_LABELS.get(str(item.get("section")), str(item.get("section") or "")), "text": str(item.get("text") or "")}
            for item in (needs_review or [])
            if isinstance(item, dict)
        ],
    }
