"""F3 round draft built only from what was said on the round.

The note quotes the clinician's exam, assessment and plan sentences. The nursing chart carries the
clinician's plan sentences as instructions plus the nurse's own acknowledgements, unchanged.
Each plan sentence becomes one proposed task. Nothing is written that nobody said.
"""

from __future__ import annotations

import re
from typing import Any

from ..extract import Sentence, analyse, claim
from .common import _segments, _transcript_event

_URGENT = re.compile(r"\b(stop|hold|check|potassium|renal)\b", re.I)
_ACKNOWLEDGEMENT = re.compile(
    r"\b(understood|noted|acknowledg\w*|will|okay|ok|got it|on it|sure)\b|\bI'll\b", re.I
)

NO_INSTRUCTIONS = "No round instructions documented"
NO_NOTE = "No round assessment, examination or plan documented"


def _key(sentence: Sentence) -> tuple[str, str]:
    return (sentence.segment_id, sentence.text)


def _in_order(analysis: Any, wanted: list[Sentence]) -> list[Sentence]:
    """The wanted sentences once each, in the order they were said."""
    keys = {_key(sentence) for sentence in wanted}
    seen: set[tuple[str, str]] = set()
    out: list[Sentence] = []
    for sentence in analysis.sentences:
        key = _key(sentence)
        if key in keys and key not in seen:
            seen.add(key)
            out.append(sentence)
    return out


def _is_acknowledgement(sentence: Sentence) -> bool:
    return not sentence.is_question and bool(_ACKNOWLEDGEMENT.search(sentence.text))


def nurse_acknowledgement_entries(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Chart entries made only from the nurse's own acknowledgements, quoted unchanged.

    Nurse questions and observations are not instructions and never become entries.
    """
    transcript_id = _transcript_event(context)
    analysis = analyse(_segments(context))
    return [claim(s, transcript_id) for s in analysis.nurse_lines if _is_acknowledgement(s)]


def f3_round(context: dict[str, Any]) -> dict[str, Any]:
    transcript_id = _transcript_event(context)
    analysis = analyse(_segments(context))

    note = _in_order(analysis, [*analysis.exam, *analysis.assessment, *analysis.plan])
    plan = _in_order(analysis, analysis.plan)
    acknowledgements = [s for s in analysis.nurse_lines if _is_acknowledgement(s)]
    chart = _in_order(analysis, [*plan, *acknowledgements])

    tasks = []
    for sentence in plan:
        urgent = bool(_URGENT.search(sentence.text))
        tasks.append(
            {
                "title": sentence.text.rstrip(".")[:110],
                "detail": f'Said on the round: "{sentence.text}"',
                "priority": "urgent" if urgent else "routine",
                "due_in_hours": 8 if urgent else 24,
                "source_segment_ids": [sentence.segment_id],
                "confidence": 0.6,
            }
        )

    not_documented = []
    if not note:
        not_documented.append(NO_NOTE)
    if not plan:
        not_documented.append(NO_INSTRUCTIONS)
    return {
        "note_claims": [claim(sentence, transcript_id) for sentence in note],
        "nursing_entries": [claim(sentence, transcript_id) for sentence in chart],
        "proposed_tasks": tasks,
        "not_documented": not_documented,
    }


GENERATORS = {"F3": f3_round}
