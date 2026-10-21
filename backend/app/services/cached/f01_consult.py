from __future__ import annotations

from typing import Any

from .common import (
    _claim,
    _seg,
    _transcript_event,
    _lab_ids,
    _patient,
)

def f1_consult_note(context: dict[str, Any]) -> dict[str, Any]:
    patient = _patient(context)
    transcript_id = _transcript_event(context)
    labs = _lab_ids(context, ["Creatinine", "eGFR", "Potassium"])
    age = patient.get("age", "")
    sex = patient.get("sex", "")
    return {
        "chief_complaint": _claim(
            "Right leg swelling, redness and pain for four days.",
            [transcript_id],
            [_seg(context, 2)],
        ),
        "hpi": _claim(
            f"{age}-year-old {str(sex).lower()} with type 2 diabetes, hypertension and CKD stage 3b "
            "reports progressive right lower leg swelling and redness since Tuesday, with warmth, "
            "pain on walking and fever last night. Denies chest pain and breathlessness.",
            [transcript_id, *labs],
            [_seg(context, 2), _seg(context, 3)],
        ),
        "exam": {
            "general": _claim(
                "Temperature 38.1°C, pulse 96, BP 138/86, SpO2 96% on room air. "
                "Right lower leg is erythematous, warm and tender with a clear demarcation; no ulcer.",
                [transcript_id],
                [_seg(context, 5)],
            ),
            "systemic": None,
        },
        "assessment": [
            _claim(
                "Cellulitis of the right lower leg.",
                [transcript_id, *labs],
                [_seg(context, 6)],
            ),
            _claim(
                "Type 2 diabetes and CKD stage 3b increase the risk of complicated infection and renal injury.",
                [transcript_id, *labs],
                [_seg(context, 6)],
            ),
        ],
        "plan": [
            _claim(
                "Admit for intravenous antibiotics and renal monitoring.",
                [transcript_id],
                [_seg(context, 6)],
            ),
            _claim(
                "Hold metformin pending review of renal function.",
                [transcript_id, *labs],
                [_seg(context, 6)],
            ),
            _claim(
                "Check potassium and creatinine today.",
                [transcript_id, *labs],
                [_seg(context, 6)],
            ),
        ],
        "medication_mentions": [
            {
                "drug": "Metformin",
                "dose": "1 g",
                "frequency": "BD",
                "source_event_ids": [transcript_id],
                "source_segment_ids": [_seg(context, 6)],
            }
        ],
        "follow_up": _claim(
            "Review creatinine and potassium on the ward before the next dose of metformin.",
            [transcript_id, *labs],
            [_seg(context, 6), _seg(context, 7)],
        ),
        "not_documented": [],
    }


GENERATORS = {"F1": f1_consult_note}
