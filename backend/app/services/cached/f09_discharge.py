"""Discharge summary without an AI key: assembled from approved notes and results, quoting them.

PRD: "Assembles the stay from documented events only, for doctor approval." Nothing here is
written by the generator. Diagnosis, course, procedures and follow-up are the sentences that
approved notes already contain, each citing the note. Red flags are never invented, so the list
stays empty. Categories with nothing documented are listed under ``not_documented``.
"""

from __future__ import annotations

import re
from typing import Any

from .common import _claim

DIAGNOSIS_NOTES = ("consult_note", "admission_note", "progress_note")
PLAN_NOTES = (("consult_note", "plan"), ("admission_note", "plan"), ("progress_note", "plan"), ("round_note", "note_claims"))

_FOLLOW_UP = re.compile(
    r"\b(follow[- ]?up|review (in|after|on)|come back|return (in|for)|next visit|re-?check|"
    r"(in|within|after)\s+(\w+\s+)?(days?|weeks?|months?))\b",
    re.I,
)


def _approved(context: dict[str, Any], type_name: str) -> list[dict[str, Any]]:
    """Approved events of one type (superseded notes are not quoted), newest first."""
    return [
        event
        for event in context.get("evidence_events", [])
        if event.get("type") == type_name and event.get("status") == "approved"
    ]


def _items(value: Any) -> list[tuple[str, float | None]]:
    """The sentences in a note field, whether stored as text, a claim, or a list of either."""
    if value is None:
        return []
    if isinstance(value, str):
        return [(value.strip(), None)] if value.strip() else []
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text.strip():
            confidence = value.get("confidence")
            return [(text.strip(), float(confidence) if isinstance(confidence, (int, float)) else None)]
        return []
    if isinstance(value, list):
        out: list[tuple[str, float | None]] = []
        for item in value:
            out.extend(_items(item))
        return out
    return []


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".").casefold()


def _quote_claims(pairs: list[tuple[str, str, float | None]]) -> list[dict[str, Any]]:
    """One claim per distinct sentence, citing every note that says it."""
    order: list[str] = []
    found: dict[str, dict[str, Any]] = {}
    for text, event_id, confidence in pairs:
        key = _key(text)
        if key not in found:
            order.append(key)
            found[key] = _claim(text, [event_id], confidence=confidence if confidence is not None else 0.9)
        elif event_id not in found[key]["source_event_ids"]:
            found[key]["source_event_ids"].append(event_id)
    return [found[key] for key in order]


def _from_notes(context: dict[str, Any], types: tuple[str, ...], field: str) -> list[dict[str, Any]]:
    pairs = []
    for type_name in types:
        for event in _approved(context, type_name):
            for text, confidence in _items((event.get("payload") or {}).get(field)):
                pairs.append((text, event["id"], confidence))
    return _quote_claims(pairs)


def _procedure_text(event: dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    return (event.get("body_text") or "").strip() or str(payload.get("procedure") or "").strip() or str(event.get("title") or "").strip()


def f9_discharge(context: dict[str, Any]) -> dict[str, Any]:
    diagnosis = _from_notes(context, DIAGNOSIS_NOTES, "assessment")
    course = _from_notes(context, ("round_note",), "note_claims")

    procedures = _quote_claims(
        [(_procedure_text(event), event["id"], None) for event in _approved(context, "procedure") if _procedure_text(event)]
    )

    labs = context.get("latest_labs", [])
    results = [
        f"{lab['name']} {lab.get('value')} {lab.get('unit', '')}".strip()
        for lab in labs
        if lab.get("name") and lab.get("value") not in (None, "")
    ]
    result_ids = [lab["event_id"] for lab in labs if lab.get("name") and lab.get("value") not in (None, "")]

    pairs: list[tuple[str, str, float | None]] = []
    for event in _approved(context, "consult_note"):
        for text, confidence in _items((event.get("payload") or {}).get("follow_up")):
            pairs.append((text, event["id"], confidence))
    for type_name, field in PLAN_NOTES:
        for event in _approved(context, type_name):
            for text, confidence in _items((event.get("payload") or {}).get(field)):
                if _FOLLOW_UP.search(text):
                    pairs.append((text, event["id"], confidence))
    follow_up = _quote_claims(pairs)

    sections = []
    not_documented = []
    for heading, claims in (
        ("Admission diagnosis", diagnosis),
        ("Hospital course", course),
        ("Procedures", procedures),
    ):
        if claims:
            sections.append({"heading": heading, "paragraphs": claims})
        else:
            not_documented.append(heading)
    if results:
        sections.append(
            {
                "heading": "Investigations",
                "paragraphs": [_claim("Latest results: " + ", ".join(results) + ".", result_ids)],
            }
        )
    else:
        not_documented.append("Investigations")
    if not follow_up:
        not_documented.append("Follow-up")
    not_documented.append("Red flags / return advice")

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
        "follow_up": follow_up,
        "red_flags": [],
        "not_documented": not_documented,
    }


GENERATORS = {"F9": f9_discharge}
