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

_EXPLICIT_URGENCY = re.compile(r"\b(urgent(?:ly)?|critical(?:ly)?|stat)\b", re.I)
_NEGATED_URGENCY = re.compile(
    r"\b(?:not|never|no|without)\s+(?:currently\s+)?(?:urgent(?:ly)?|critical(?:ly)?|stat)\b",
    re.I,
)
_NURSE_ACTION = re.compile(
    r"\b(nurse|observations?|obs|vitals?|monitor|monitoring|wound care|dressing|chart|charted|record obs|"
    r"collect (?:a )?(?:sample|specimen|bloods?)|fluid balance|intake and output)\b",
    re.I,
)
_SENIOR_ACTION = re.compile(r"\b(senior doctor|consultant|attending)\b", re.I)
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
        urgency = explicit_urgency(sentence.text) if sentence.role == "clinician" else "routine"
        tasks.append(
            {
                "title": sentence.text.rstrip(".")[:110],
                "detail": f'Said on the round: "{sentence.text}"',
                "priority": urgency,
                "assignee_role": infer_assignee_role(sentence.text),
                "due_in_hours": 1 if urgency == "critical" else 4 if urgency == "urgent" else 24,
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
        "report": {
            "findings": [claim(sentence, transcript_id) for sentence in analysis.exam],
            "assessment": [claim(sentence, transcript_id) for sentence in analysis.assessment],
            "plan": [claim(sentence, transcript_id) for sentence in analysis.plan],
        },
        "nursing_entries": [claim(sentence, transcript_id) for sentence in chart],
        "proposed_tasks": tasks,
        "not_documented": not_documented,
    }


GENERATORS = {"F3": f3_round}


def explicit_urgency(text: str) -> str:
    """Return a priority only for an explicit, non-negated urgency word."""
    positive_text = _NEGATED_URGENCY.sub("", text)
    words = [match.group(1).lower() for match in _EXPLICIT_URGENCY.finditer(positive_text)]
    if "critical" in words or "critically" in words:
        return "critical"
    if "urgent" in words or "urgently" in words or "stat" in words:
        return "urgent"
    return "routine"


def infer_assignee_role(text: str) -> str:
    """Map bedside/nursing work to nurses; otherwise route clinical follow-up to junior doctors."""
    if _SENIOR_ACTION.search(text):
        return "senior_doctor"
    if _NURSE_ACTION.search(text):
        return "nurse"
    return "junior_doctor"


def normalize_round_tasks(content: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Enforce source-based urgency and role mapping on model or cached F3 proposals."""
    if not isinstance(content, dict):
        return content
    segments = {str(item.get("segment_id", "")): item for item in _segments(context)}
    report = dict(content.get("report") or {})
    report.setdefault("findings", [])
    report.setdefault("assessment", [])
    report.setdefault("plan", [])
    if not all(report.get(key) for key in ("findings", "assessment", "plan")):
        analysis = analyse(_segments(context))
        transcript_id = _transcript_event(context)
        for key, sentences in (
            ("findings", analysis.exam),
            ("assessment", analysis.assessment),
            ("plan", analysis.plan),
        ):
            if not report[key]:
                report[key] = [claim(sentence, transcript_id) for sentence in sentences]
    tasks = []
    for raw in content.get("proposed_tasks", []) or []:
        if not isinstance(raw, dict):
            continue
        task = dict(raw)
        cited_segments = [segments[item] for item in task.get("source_segment_ids", []) if item in segments]
        source_text = " ".join(str(segment.get("text", "")) for segment in cited_segments)
        clinician_text = " ".join(
            str(segment.get("text", ""))
            for segment in cited_segments
            if str(segment.get("speaker", "")).strip().lower() not in {"nurse", "nursing", "patient", "ravi"}
        )
        task_text = " ".join((str(task.get("title", "")), str(task.get("detail", "")), source_text))
        task["priority"] = explicit_urgency(clinician_text)
        task["assignee_role"] = infer_assignee_role(task_text)
        if task["priority"] == "critical":
            task["due_in_hours"] = 1
        elif task["priority"] == "urgent":
            task["due_in_hours"] = min(int(task.get("due_in_hours", 4) or 4), 4)
        tasks.append(task)
    return {**content, "report": report, "proposed_tasks": tasks}
