from __future__ import annotations

from typing import Any

from .common import (
    _claim,
    _seg,
    _transcript_event,
    _lab_ids,
    _patient,
)

def f2_admission_note(context: dict[str, Any]) -> dict[str, Any]:
    patient = _patient(context)
    transcript_id = _transcript_event(context)
    labs = _lab_ids(context, ["Creatinine", "eGFR", "Potassium", "HbA1c"])
    problems = ", ".join(patient.get("problems", [])) or "no documented comorbidities"
    return {
        "chief_complaint": _claim(
            "Right lower leg cellulitis requiring inpatient intravenous antibiotics.",
            [transcript_id],
            [_seg(context, 1)],
        ),
        "history": _claim(
            f"Admitted with a four-day history of a red, warm, painful right leg and fever. "
            f"Background of {problems}. Penicillin allergy documented.",
            [transcript_id, *labs],
            [_seg(context, 2), _seg(context, 3)],
        ),
        "exam": {
            "general": _claim(
                "Febrile at 38.1°C, haemodynamically stable. Right lower leg erythema with demarcation and tenderness, no ulceration.",
                [transcript_id],
                [_seg(context, 4)],
            ),
            "systemic": None,
        },
        "assessment": [
            _claim(
                "Right lower leg cellulitis on a background of diabetes and CKD stage 3b.",
                [transcript_id, *labs],
                [_seg(context, 5)],
            )
        ],
        "plan": [
            _claim(
                "Intravenous antibiotics, renal monitoring and daily wound review.",
                [transcript_id],
                [_seg(context, 5)],
            )
        ],
        "proposed_orders": [
            {
                "order": "IV antibiotic with non-penicillin coverage",
                "rationale": "Documented penicillin allergy; cellulitis requires inpatient cover.",
                "source_event_ids": [transcript_id],
            },
            {
                "order": "Creatinine, eGFR and potassium now and daily",
                "rationale": "CKD stage 3b and metformin exposure.",
                "source_event_ids": labs,
            },
        ],
        "allergies_to_verify": [
            {
                "substance": item.get("substance", "") if isinstance(item, dict) else str(item),
                "reaction": item.get("reaction", "") if isinstance(item, dict) else "",
                "source_event_id": item.get("event_id", "") if isinstance(item, dict) else "",
                "verified": False,
            }
            for item in patient.get("allergies", [])
        ],
        "not_documented": [],
    }


GENERATORS = {"F2": f2_admission_note}
