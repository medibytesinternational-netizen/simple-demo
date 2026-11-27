"""Validation and presentation helpers for MediBytes' six-section note payload."""

from __future__ import annotations

import json
from typing import Any


NOTE_SECTIONS = (
    ("present_illness", "Present illness"),
    ("examination_findings", "Examination findings"),
    ("previous_diagnosis", "Previous diagnosis"),
    ("plan_of_management", "Plan of management"),
    ("diet_instructions", "Diet instructions"),
    ("general_instructions", "General instructions"),
)
NOTE_FIELDS = tuple(field for field, _ in NOTE_SECTIONS)


class MediBytesNoteError(ValueError):
    """The response string does not match the documented HIMS note contract."""


def parse_note_response(response: str) -> dict[str, str]:
    """Parse the documented one-row JSON array without filling empty sections."""
    if not isinstance(response, str) or not response.strip():
        raise MediBytesNoteError("MediBytes note response is empty")
    try:
        rows: Any = json.loads(response)
    except (TypeError, json.JSONDecodeError):
        raise MediBytesNoteError("MediBytes note response is not valid JSON") from None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise MediBytesNoteError("MediBytes note response must be a JSON array containing one object")
    row = rows[0]
    missing = [field for field in NOTE_FIELDS if field not in row]
    extra = sorted(set(row) - set(NOTE_FIELDS))
    if missing:
        raise MediBytesNoteError(f"MediBytes note is missing section(s): {', '.join(missing)}")
    if extra:
        raise MediBytesNoteError(f"MediBytes note contains unsupported section(s): {', '.join(extra)}")
    invalid = [field for field in NOTE_FIELDS if not isinstance(row[field], str)]
    if invalid:
        raise MediBytesNoteError(f"MediBytes note section(s) must be strings: {', '.join(invalid)}")
    return {field: row[field] for field in NOTE_FIELDS}


def format_note_sections(note: dict[str, str]) -> str:
    """Make the exact six fields readable without adding facts or filler."""
    return "\n\n".join(f"{label}:\n{note[field]}" for field, label in NOTE_SECTIONS)


def note_segments(note: dict[str, str]) -> list[dict[str, Any]]:
    """Expose only non-empty source text; the API provides no per-section timestamps."""
    segments = []
    for index, (field, label) in enumerate(NOTE_SECTIONS, start=1):
        value = note[field]
        if not value.strip():
            continue
        segments.append(
            {
                "segment_id": f"seg_{index}",
                "index": index,
                "speaker": "MediBytes",
                "section": field,
                "text": value,
                "label": label,
            }
        )
    return segments
