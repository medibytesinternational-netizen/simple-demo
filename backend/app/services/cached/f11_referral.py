from __future__ import annotations

from typing import Any

from .common import (
    _claim,
    _first,
    _lab,
    _patient,
)

def f11_referral(context: dict[str, Any]) -> dict[str, Any]:
    patient = _patient(context)
    admission = _first(context, "admission_note")
    round_event = _first(context, "round_note")
    labs = context.get("latest_labs", [])
    lab_ids = [lab["event_id"] for lab in labs]
    evidence = [item for item in [admission["id"] if admission else "", round_event["id"] if round_event else "", *lab_ids] if item]
    egfr = _lab(context, "eGFR")
    creatinine = _lab(context, "Creatinine")
    question = (
        "Does this patient with CKD stage 3b and eGFR 22 need nephrology co-management, "
        "medication dose adjustment or dialysis planning during this admission?"
    )
    if egfr and creatinine:
        question = (
            f"Does this patient with eGFR {egfr.get('value')} mL/min/1.73m² and creatinine "
            f"{creatinine.get('value')} need nephrology co-management, medication dose adjustment "
            "or dialysis planning during this admission?"
        )
    return {
        "specialty": "Nephrology",
        "specialist": "Nephrology on-call service",
        "question": _claim(question, evidence),
        "history": _claim(
            "58-year-old man with type 2 diabetes, hypertension and CKD stage 3b, admitted with "
            "right lower leg cellulitis. Renal function is impaired and metformin remains on the active order list "
            "pending review. Potassium is at the upper limit of normal.",
            evidence,
        ),
        "urgency": "urgent",
        "relevant_results": [
            _claim(
                f"{lab['name']} {lab.get('value')} {lab.get('unit', '')}".strip(),
                [lab["event_id"]],
            )
            for lab in labs
            if str(lab.get("flag", "")).lower() in {"high", "low"}
        ],
        "source_event_ids": evidence,
    }


GENERATORS = {"F11": f11_referral}
