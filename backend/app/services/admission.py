"""The hospital's admission note format, and how it is filled.

Record headings (name, sex, age, OP number, date, consultant) come from registration and the visit.
The rest come from the admission recording. A heading the recording does not mention is filled from
the patient's signed OPD report where that report has it. The recording always wins; each item says
where it came from (``origin``: "recording" or "opd").
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Encounter, Patient, TimelineEvent
from ..schemas import ADMISSION_HEARD_SECTIONS

ADMIT_FORMAT = "admit_v2"

ADMISSION_HEADER_FIELDS: list[tuple[str, str]] = [
    ("name", "Name"),
    ("sex", "Sex"),
    ("age", "Age"),
    ("op_number", "OP number"),
    ("date_of_admission", "On (date of admission)"),
    ("consultant", "Under (consultant)"),
]

# Admission heading <- OPD report heading it may be filled from when the recording is silent.
FROM_OPD: dict[str, str] = {
    "allergies": "allergies",
}


def admission_header(patient: Patient, encounter: Encounter, consultant: str, admitted_at: str = "") -> dict[str, str]:
    return {
        "name": patient.name or "",
        "sex": patient.sex or "",
        "age": f"{patient.age} years" if patient.age is not None else "",
        "op_number": patient.mrn or "",
        "date_of_admission": admitted_at,
        "consultant": consultant or encounter.attending or "",
    }


def latest_opd_report(db: Session, patient_id: str) -> TimelineEvent | None:
    """The patient's current signed OPD report in the hospital format, if any."""
    events = db.scalars(
        select(TimelineEvent)
        .where(
            TimelineEvent.patient_id == patient_id,
            TimelineEvent.type == "consult_note",
            TimelineEvent.status == "approved",
        )
        .order_by(TimelineEvent.occurred_at.desc())
    ).all()
    return next((e for e in events if (e.payload or {}).get("format") == "opd_v2"), None)


def _tag(value: Any, origin: str) -> Any:
    if isinstance(value, list):
        return [_tag(v, origin) for v in value]
    if isinstance(value, dict) and value.get("text"):
        return {**value, "origin": value.get("origin") or origin}
    return value


def _empty(value: Any) -> bool:
    return not value or (isinstance(value, dict) and not str(value.get("text") or "").strip())


def merge_with_opd(content: dict[str, Any], opd: TimelineEvent | None) -> dict[str, Any]:
    """Recording first; the signed OPD report fills headings the recording left empty."""
    merged = dict(content)
    for key, _label, _many in ADMISSION_HEARD_SECTIONS:
        merged[key] = _tag(merged.get(key), "recording")
    if opd is not None:
        payload = opd.payload or {}
        for key, opd_key in FROM_OPD.items():
            if _empty(merged.get(key)) and not _empty(payload.get(opd_key)):
                found = _tag(payload.get(opd_key), "opd")
                # OPD items cite the OPD report itself, which is on the timeline.
                if isinstance(found, list):
                    found = [{**c, "source_event_ids": [opd.id], "source_segment_ids": []} for c in found]
                merged[key] = found
    merged["not_documented"] = not_documented(merged)
    return merged


def not_documented(content: dict[str, Any]) -> list[str]:
    return [label for key, label, _many in ADMISSION_HEARD_SECTIONS if _empty(content.get(key))]


__all__ = [
    "ADMIT_FORMAT", "ADMISSION_HEADER_FIELDS", "ADMISSION_HEARD_SECTIONS",
    "admission_header", "latest_opd_report", "merge_with_opd", "not_documented",
]
