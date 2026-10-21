from __future__ import annotations

from typing import Any

from .common import (
    _claim,
    _first,
    _lab,
)

def f9_discharge(context: dict[str, Any]) -> dict[str, Any]:
    consult = _first(context, "consult_note")
    admission = _first(context, "admission_note")
    round_event = _first(context, "round_note")
    progress = _first(context, "progress_note")
    procedure = _first(context, "procedure")
    labs = context.get("latest_labs", [])
    lab_ids = [lab["event_id"] for lab in labs]
    discharge_event_ids = [
        item["id"] for item in (consult, admission, round_event, progress, procedure) if item
    ]
    creatinine = _lab(context, "Creatinine")
    egfr = _lab(context, "eGFR")
    potassium = _lab(context, "Potassium")
    sections = [
        {
            "heading": "Admission diagnosis",
            "paragraphs": [
                _claim(
                    "Right lower leg cellulitis in a patient with type 2 diabetes, hypertension and CKD stage 3b.",
                    discharge_event_ids or lab_ids,
                )
            ],
        },
        {
            "heading": "Hospital course",
            "paragraphs": [
                _claim(
                    "Admitted for intravenous antibiotics with daily wound review. Renal function was monitored, and the discharge medication list was assembled from active orders for clinician review.",
                    [*( [round_event["id"]] if round_event else []), *lab_ids],
                )
            ],
        },
    ]
    if procedure:
        sections.append(
            {
                "heading": "Procedures",
                "paragraphs": [
                    _claim(
                        f"{(procedure.get('payload') or {}).get('procedure', 'Wound debridement')} performed during the admission.",
                        [procedure["id"]],
                    )
                ],
            }
        )
    investigations = []
    if creatinine:
        investigations.append(
            f"creatinine {creatinine.get('value')} {creatinine.get('unit', '')}".strip()
        )
    if egfr:
        investigations.append(f"eGFR {egfr.get('value')} mL/min/1.73m²")
    if potassium:
        investigations.append(f"potassium {potassium.get('value')} {potassium.get('unit', '')}".strip())
    if investigations:
        sections.append(
            {
                "heading": "Investigations",
                "paragraphs": [
                    _claim(
                        "Latest results: " + ", ".join(investigations) + ".",
                        lab_ids,
                    )
                ],
            }
        )
    pending = [
        _claim(
            f"{lab['name']} remains unreviewed and should be checked before the next clinical contact.",
            [lab["event_id"]],
        )
        for lab in context.get("unreviewed_labs", [])
    ]
    return {
        "sections": sections,
        "medications": [],
        "pending_results": pending,
        "follow_up": [
            _claim(
                "Repeat creatinine, eGFR and potassium within one week.",
                lab_ids,
            )
        ],
        "red_flags": [
            _claim(
                "Return urgently if fever, spreading redness, breathlessness or reduced urine output develops.",
                (discharge_event_ids or lab_ids),
                confidence=0.8,
            )
        ],
        "not_documented": [],
    }


GENERATORS = {"F9": f9_discharge}
