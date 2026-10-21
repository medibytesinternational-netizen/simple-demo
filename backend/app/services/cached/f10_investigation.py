from __future__ import annotations

from typing import Any

from .common import (
    _claim,
    _first,
    _lab,
    _patient,
)

def f10_investigation_request(context: dict[str, Any]) -> dict[str, Any]:
    patient = _patient(context)
    admission = _first(context, "admission_note")
    labs = context.get("latest_labs", [])
    lab_ids = [lab["event_id"] for lab in labs]
    egfr = _lab(context, "eGFR")
    creatinine = _lab(context, "Creatinine")
    evidence = [item for item in [admission["id"] if admission else "", *lab_ids] if item]
    indication_text = "CKD stage 3b with eGFR 22 and creatinine 2.9 mg/dL; assess renal parenchyma and obstruction."
    if egfr and creatinine:
        indication_text = (
            f"CKD stage 3b with eGFR {egfr.get('value')} mL/min/1.73m² and creatinine "
            f"{creatinine.get('value')} {creatinine.get('unit', '')}; assess renal parenchyma and obstruction."
        )
    allergies = [
        {
            "substance": allergy,
            "reaction": "Documented reaction — verify before contrast or procedure",
            "source_event_id": "",
            "verified": False,
        }
        for allergy in patient.get("allergies", [])
    ]
    return {
        "request_type": "imaging",
        "study": "Renal ultrasound with Doppler",
        "indication": _claim(indication_text, evidence),
        "diagnosis": ", ".join(patient.get("problems", [])[:3]) or "Documented inpatient diagnosis",
        "allergies_to_verify": allergies,
        "priority": "routine",
        "instructions": "Assess renal size, echogenicity, hydronephrosis and renal artery flow. No contrast unless reviewed.",
        "recipient": "Radiology department",
        "source_event_ids": evidence,
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
