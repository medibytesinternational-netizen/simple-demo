"""F2 admission note without an AI key, in the hospital admission format.

Every item quotes a sentence that was said in the admission dictation and cites its segment. A
heading nobody spoke about stays empty; when the draft is created it is filled from the patient's
signed OPD report where that report has it, and otherwise listed under ``not_documented``.
Proposed treatment is a proposal: signing the note never places an order.
"""

from __future__ import annotations

import re
from typing import Any

from ..extract import analyse, claim, joined_claim
from .common import _segments, _transcript_event

_FIND: dict[str, re.Pattern[str]] = {
    "admission_type": re.compile(r"\b(elective|emergency|emergent|urgent admission)\b", re.I),
    "ward": re.compile(r"\b(admit(?:ted|ting)? (?:him|her|them|the patient)? ?(?:to|in(?:to)?)|ward\s*\d*|icu|hdu|ccu|nicu)\b", re.I),
    "speciality": re.compile(r"\b(under (?:the )?(?:general )?(?:medicine|surgery|cardiology|neurology|orthopaedics|orthopedics|gynaecology|paediatrics|pediatrics|nephrology|pulmonology|gastroenterology|oncology)|speciality|department of)\b", re.I),
    "provisional_diagnosis": re.compile(r"\b(provisional diagnosis|working diagnosis|diagnosis is|most likely|looks like|suggestive of|consistent with)\b", re.I),
    "proposed_treatment": re.compile(r"\b(start|give|continue|commence|infuse|iv |intravenous|tablet|tab |injection|surgery|procedure|operation|oxygen|nebuli[sz]|physiotherapy|dialysis)\b", re.I),
    "expected_outcome": re.compile(r"\b(expect(?:ed)? (?:him|her|them|it)? ?to (?:improve|recover|stay|remain|worsen|deteriorate)|should improve|prognosis|outcome)\b", re.I),
    "possible_complications": re.compile(r"\b(risk of|complication|may develop|could develop|watch (?:out )?for)\b", re.I),
    "allergies": re.compile(r"\ballerg(?:y|ies|ic)\b", re.I),
    "cost_category": re.compile(r"\b(cost|insurance|scheme|category|package|rupees|rs\.?|lakh|thousand|general ward rate|private)\b", re.I),
    "admission_labs": re.compile(r"\b(cbc|complete blood count|blood (?:test|culture|sugar|count)|renal function|kidney function|liver function|lft|rft|electrolytes|urine|culture|hba1c|troponin|coagulation|lab(?:oratory)?s?)\b", re.I),
    "imaging_studies": re.compile(r"\b(x-?ray|ultrasound|usg|ct\b|ct scan|mri|echo(?:cardiogram)?|scan|doppler)\b", re.I),
    "consultations_required": re.compile(r"\b(opinion|consult(?:ation)?|refer(?:ral)? to|review by|see (?:the )?\w+ team)\b", re.I),
}
_SINGLE = {"admission_type", "ward", "speciality", "expected_outcome", "cost_category"}


def f2_admission_note(context: dict[str, Any]) -> dict[str, Any]:
    tid = _transcript_event(context)
    analysis = analyse(_segments(context))
    said = [s for s in analysis.sentences if not s.is_question]
    content: dict[str, Any] = {"format": "admit_v2"}
    for key, rx in _FIND.items():
        found = [s for s in said if rx.search(s.text)]
        content[key] = joined_claim(found[:1], tid) if key in _SINGLE else [claim(s, tid) for s in found]
    return content


GENERATORS = {"F2": f2_admission_note}
