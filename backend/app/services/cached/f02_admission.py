"""F2 admission draft without an AI key.

Built only from what was said (quoted verbatim through services/extract.py) and from records
already held (home medicines, abnormal latest results, problems and allergies on the patient
record). A section with no source stays empty. Proposed orders are proposals: approving the
note never creates an order.
"""

from __future__ import annotations

import re
from typing import Any

from ..extract import analyse, claim, joined_claim, medicines_in
from .common import _home_meds, _patient, _segments, _transcript_event

ORDER_RATIONALE = "Said in the admission conversation"
_ABNORMAL_WORDS = ("high", "low", "critical")


def _is_abnormal(lab: dict[str, Any]) -> bool:
    flag = str(lab.get("flag") or "").lower()
    return any(word in flag for word in _ABNORMAL_WORDS)


def _medicine_text(med: dict[str, Any]) -> str:
    parts = [str(med.get("drug", "")).strip(), str(med.get("dose", "")).strip(), str(med.get("frequency", "")).strip()]
    return " ".join(part for part in parts if part)


def _lab_text(lab: dict[str, Any]) -> str:
    value = " ".join(str(item) for item in (lab.get("value"), lab.get("unit")) if item not in (None, ""))
    return f"{lab.get('name', '')} {value} ({str(lab.get('flag', '')).lower()})".replace("  ", " ").strip()


def _history_claim(context: dict[str, Any], analysis, transcript_id: str) -> dict[str, Any] | None:
    pieces: list[str] = []
    event_ids: list[str] = []
    segment_ids: list[str] = []
    confidence = 0.9

    transcript_part = joined_claim(analysis.history, transcript_id)
    if transcript_part:
        pieces.append(transcript_part["text"])
        event_ids.extend(transcript_part["source_event_ids"])
        segment_ids.extend(transcript_part["source_segment_ids"])
        confidence = transcript_part["confidence"]

    meds = [med for med in _home_meds(context) if _medicine_text(med)]
    if meds:
        pieces.append("Home medicines on record: " + ", ".join(_medicine_text(med) for med in meds) + ".")
        event_ids.extend(str(med.get("event_id", "")) for med in meds)

    labs = [lab for lab in context.get("latest_labs", []) if _is_abnormal(lab) and lab.get("name")]
    if labs:
        pieces.append("Abnormal latest results: " + ", ".join(_lab_text(lab) for lab in labs) + ".")
        event_ids.extend(str(lab.get("event_id", "")) for lab in labs)

    problems = [str(item).strip() for item in _patient(context).get("problems", []) if str(item).strip()]
    if problems:
        pieces.append("On the patient record: " + ", ".join(problems) + ".")

    if not pieces:
        return None
    return {
        "text": " ".join(pieces),
        "source_event_ids": list(dict.fromkeys(item for item in event_ids if item)),
        "source_segment_ids": list(dict.fromkeys(segment_ids)),
        "confidence": confidence,
    }


def _proposed_orders(analysis, transcript_id: str) -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sentence in analysis.plan:
        names_medicine = bool(medicines_in(sentence))
        # "Review in four weeks" is a follow-up appointment, not an order.
        if re.match(r"\s*review\b", sentence.text, re.I) and not names_medicine:
            continue
        if sentence.text in seen:
            continue
        seen.add(sentence.text)
        orders.append(
            {
                "order": sentence.text,
                "rationale": ORDER_RATIONALE,
                "source_event_ids": [transcript_id] if transcript_id else [],
                "source_segment_ids": [sentence.segment_id],
            }
        )
    return orders


def _allergy_event(context: dict[str, Any], substance: str) -> dict[str, Any] | None:
    wanted = substance.lower()
    for event in context.get("evidence_events", []):
        if event.get("type") != "allergy_record":
            continue
        recorded = str((event.get("payload") or {}).get("substance", "")).strip().lower()
        if recorded and (recorded == wanted or recorded in wanted or wanted in recorded):
            return event
    return None


def _allergies(context: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for item in _patient(context).get("allergies", []):
        if isinstance(item, dict):
            raw_substance = str(item.get("substance", ""))
            reaction = str(item.get("reaction", "") or "")
            event_id = str(item.get("event_id", "") or "")
        else:
            raw_substance, reaction, event_id = str(item), "", ""
        substance, _, tail = raw_substance.partition(" — ")
        substance = substance.strip()
        if not substance:
            continue
        if not reaction:
            reaction = tail.strip()
        if not event_id or not reaction:
            event = _allergy_event(context, substance)
            if event:
                event_id = event_id or str(event.get("id", ""))
                reaction = reaction or str((event.get("payload") or {}).get("reaction", "") or "")
        out.append(
            {
                "substance": substance,
                "reaction": reaction,
                "source_event_id": event_id,
                "verified": False,
            }
        )
    return out


def f2_admission_note(context: dict[str, Any]) -> dict[str, Any]:
    transcript_id = _transcript_event(context)
    analysis = analyse(_segments(context))
    # A follow-up sentence that merely mentions "peak flow" or similar is not an examination finding.
    exam = [sentence for sentence in analysis.exam if sentence not in analysis.follow_up]
    return {
        "chief_complaint": claim(analysis.complaint, transcript_id) if analysis.complaint else None,
        "history": _history_claim(context, analysis, transcript_id),
        "exam": {
            "general": joined_claim(exam, transcript_id),
            "systemic": None,
        },
        "assessment": [claim(sentence, transcript_id) for sentence in analysis.assessment],
        "plan": [claim(sentence, transcript_id) for sentence in analysis.plan],
        "proposed_orders": _proposed_orders(analysis, transcript_id),
        "allergies_to_verify": _allergies(context),
        "not_documented": analysis.missing(),
    }


GENERATORS = {"F2": f2_admission_note}
