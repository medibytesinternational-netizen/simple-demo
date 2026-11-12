"""Client for the MediBytes transcription pipeline API (audio -> six-section note).

Upload answers 202 with a receipt; the finished note is pulled with the status call.
See "API Documentation.pdf" (MediBytes API — Guide).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import HTTPException

from ..config import settings

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

_UPLOAD_ERRORS = {
    400: "The audio file is empty",
    401: "Pipeline API key is missing or wrong",
    413: "Audio too large (max 64 MB)",
    415: "That file type is not supported by the pipeline",
    422: "The recording id was not accepted by the pipeline",
    503: "The MediBytes pipeline is not ready; try again shortly",
}


def configured() -> bool:
    return bool(settings.medibytes_api_key)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.medibytes_api_key}"}


def _base() -> str:
    return settings.medibytes_base_url.rstrip("/")


def submit(contents: bytes, filename: str, content_type: str, audio_id: str) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"{_base()}/api/v1/transcriptions",
            headers=_headers(),
            files={"file": (filename, contents, content_type)},
            data={"audio_id": audio_id, "company_id": str(settings.medibytes_company_id)},
            timeout=120,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach the MediBytes pipeline: {exc}") from exc
    if response.status_code != 202:
        message = _UPLOAD_ERRORS.get(response.status_code, f"Pipeline upload failed [{response.status_code}]")
        status = response.status_code if response.status_code in (400, 413, 415, 422) else 502
        raise HTTPException(status, message)
    return response.json()


def fetch(audio_id: str) -> dict[str, Any] | None:
    try:
        response = httpx.get(f"{_base()}/api/v1/transcriptions/{audio_id}", headers=_headers(), timeout=30)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach the MediBytes pipeline: {exc}") from exc
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise HTTPException(502, f"Pipeline status failed [{response.status_code}]")
    return response.json()


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
