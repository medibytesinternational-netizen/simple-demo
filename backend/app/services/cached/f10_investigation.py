from __future__ import annotations

import re
from typing import Any

from .common import (
    _claim,
    _lab,
    _patient,
)

NORMAL_FLAGS = {"", "normal", "unknown"}
IMAGING_RE = re.compile(
    r"ultrasound|x-?ray|radiograph|\bct\b|\bmri\b|\bscan|echo|doppler|imaging|mammogra|fluoroscop|\bpet\b",
    re.IGNORECASE,
)


def abnormal_results(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Latest results the record flags as abnormal, renal ones first."""
    found = [
        lab
        for lab in context.get("latest_labs", [])
        if str(lab.get("flag", "")).strip().lower() not in NORMAL_FLAGS and lab.get("event_id")
    ]
    renal = {"egfr", "creatinine"}
    return sorted(found, key=lambda lab: (str(lab.get("name", "")).lower() not in renal, str(lab.get("name", "")).lower()))


def _renal_abnormal(context: dict[str, Any]) -> bool:
    egfr = _lab(context, "eGFR")
    creatinine = _lab(context, "Creatinine")
    return bool(
        (egfr and str(egfr.get("flag", "")).lower() == "low")
        or (creatinine and str(creatinine.get("flag", "")).lower() == "high")
    )


def _infer_type(study: str) -> str:
    return "imaging" if IMAGING_RE.search(study) else "laboratory"


def resolve_study(
    context: dict[str, Any], study: str | None = None, request_type: str | None = None
) -> tuple[str, str]:
    """Pick the study and its type. Raises ValueError when nothing supports a choice."""
    study = (study or "").strip()
    if study:
        return study, request_type or _infer_type(study)
    if _renal_abnormal(context):
        return "Renal ultrasound", request_type or "imaging"
    abnormal = abnormal_results(context)
    if abnormal:
        names = ", ".join(str(lab.get("name", "")) for lab in abnormal)
        return f"Repeat {names}", request_type or "laboratory"
    raise ValueError("Choose the study to request")


def _result_text(lab: dict[str, Any]) -> str:
    value = f"{lab.get('value', '')} {lab.get('unit', '')}".strip()
    return f"{lab.get('name', '')} {value} ({str(lab.get('flag', '')).lower()})"


def _allergies_to_verify(patient: dict[str, Any]) -> list[dict[str, Any]]:
    """Substance and reaction split, each citing its allergy record event (as the F2 form does)."""
    out = []
    for item in patient.get("allergies", []):
        if isinstance(item, dict):
            raw, reaction, event_id = str(item.get("substance", "")), str(item.get("reaction", "") or ""), str(item.get("event_id", "") or "")
        else:
            raw, reaction, event_id = str(item), "", ""
        substance, _, tail = raw.partition(" — ")
        substance = substance.strip()
        if not substance:
            continue
        out.append(
            {
                "substance": substance,
                "reaction": reaction or tail.strip(),
                "source_event_id": event_id,
                "verified": False,
            }
        )
    return out


def f10_investigation_request(context: dict[str, Any]) -> dict[str, Any]:
    patient = _patient(context)
    if context.get("requested_study"):
        study, request_type = resolve_study(context, context["requested_study"], context.get("requested_type"))
    else:
        study, request_type = resolve_study(context, None, context.get("requested_type"))
    abnormal = abnormal_results(context)
    result_ids = [lab["event_id"] for lab in abnormal]
    if abnormal:
        indication = _claim("Abnormal results: " + ", ".join(_result_text(lab) for lab in abnormal), result_ids)
    else:
        indication = _claim("", [], confidence=0.0)
    allergies = _allergies_to_verify(patient)
    return {
        "request_type": request_type,
        "study": study,
        "indication": indication,
        "diagnosis": ", ".join(patient.get("problems", [])),
        "allergies_to_verify": allergies,
        "priority": "routine",
        "instructions": "",
        "recipient": "Radiology department" if request_type == "imaging" else "Laboratory",
        "source_event_ids": result_ids,
    }


def f10_document_request(context: dict[str, Any]) -> dict[str, Any]:
    extra = context.get("revenue", {}) or {}
    missing = extra.get("missing_documents", [])
    records = [item.get("label", item.get("key", "Document")) for item in missing]
    if not records:
        records = ["Signed discharge summary"]
    evidence = []
    for item in missing:
        evidence.extend(item.get("evidence_event_ids", []))
    if not evidence:
        events = context.get("evidence_events", [])
        evidence = [events[0]["id"]] if events else []
    return {
        "request_type": "pre_auth" if any("pre-auth" in str(record).lower() for record in records) else "records",
        "recipient": extra.get("recipient", "Hospital records department"),
        "records_requested": records,
        "justification": _claim(
            "These items are required before the claim pack can enter clinical review. Missing documentation blocks review; no submission is attempted.",
            evidence,
        ),
        "due_in_days": 3,
        "source_event_ids": evidence,
    }


GENERATORS = {"F10": f10_investigation_request}
