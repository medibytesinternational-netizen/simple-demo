"""The hospital's OPD note format: the record headings and the order of every heading."""

from __future__ import annotations

from typing import Any

from ..models import Encounter, Patient
from ..schemas import OPD_HEARD_SECTIONS

OPD_FORMAT = "opd_v2"

# Record headings, in the format's order: (key in the header, label).
OPD_HEADER_FIELDS: list[tuple[str, str]] = [
    ("patient_name", "Patient name"),
    ("age_sex", "Age and sex"),
    ("date_of_admission", "Date of admission"),
    ("hospital_number", "Hospital number"),
    ("department", "Department"),
    ("unit_consultant", "Unit and consultant"),
    ("recorded_by", "History and physical recorded by"),
]

DEPARTMENTS = {"OPD": "Outpatient department (OPD)", "IPD": "Inpatient", "Day care": "Day care"}


def opd_header(patient: Patient, encounter: Encounter, recorded_by: str) -> dict[str, str]:
    """The record part of the note, from registration and the visit; nothing here is heard."""
    sex = (patient.sex or "").strip()
    return {
        "patient_name": patient.name or "",
        "age_sex": f"{patient.age} years / {sex}" if sex else f"{patient.age} years",
        "date_of_admission": encounter.admitted_at.strftime("%d %b %Y, %H:%M") if encounter.admitted_at else "",
        "hospital_number": patient.mrn or "",
        "department": DEPARTMENTS.get(encounter.kind or "", encounter.kind or ""),
        "unit_consultant": encounter.attending or "",
        "recorded_by": recorded_by,
    }


def heard_not_documented(content: dict[str, Any]) -> list[str]:
    """Labels of heard headings nobody spoke about."""
    return [label for key, label in OPD_HEARD_SECTIONS if not content.get(key)]


__all__ = ["OPD_FORMAT", "OPD_HEADER_FIELDS", "OPD_HEARD_SECTIONS", "opd_header", "heard_not_documented"]
