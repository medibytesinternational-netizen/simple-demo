"""Daily progress note drafted from what changed since the last note.

Subjective and assessment quote the transcript. Objective is built only from timeline events and
alerts recorded after the previous note, each cited by event id. Examination and plan are left for
the clinician and always listed as not documented.
"""

from __future__ import annotations

from typing import Any

from ..extract import analyse, claim, joined_claim
from .common import _claim, _segments, _transcript_event


def _lab_line(payload: dict[str, Any], title: str) -> str:
    name = str(payload.get("name") or "").strip()
    if not name:
        return title
    parts = [name, str(payload.get("value", "")).strip(), str(payload.get("unit", "")).strip()]
    line = " ".join(part for part in parts if part)
    flag = str(payload.get("flag") or "").strip().lower()
    if flag and flag != "unknown":
        line += f" ({flag})"
    return line


def _vitals_line(payload: dict[str, Any]) -> str:
    bits = []
    if payload.get("temperature_c") is not None:
        bits.append(f"temperature {payload['temperature_c']}°C")
    if payload.get("heart_rate") is not None:
        bits.append(f"heart rate {payload['heart_rate']} bpm")
    if payload.get("systolic") is not None and payload.get("diastolic") is not None:
        bits.append(f"BP {payload['systolic']}/{payload['diastolic']}")
    if payload.get("respiratory_rate") is not None:
        bits.append(f"respiratory rate {payload['respiratory_rate']}")
    if payload.get("spo2") is not None:
        bits.append(f"SpO2 {payload['spo2']}%")
    return "Vitals: " + ", ".join(bits) if bits else ""


def _order_line(payload: dict[str, Any], title: str) -> str:
    drug = " ".join(str(payload.get(key, "")).strip() for key in ("drug", "dose", "frequency")).strip()
    if not str(payload.get("drug", "")).strip():
        return title
    state = "stopped" if payload.get("status") == "stopped" else "started"
    return f"{drug} {state}"


def _objective(context: dict[str, Any]) -> dict[str, Any] | None:
    since = context.get("since_last") or {}
    previous = context.get("previous_note")
    lines: list[str] = []
    cited: list[str] = []
    for event in since.get("events", []):
        payload = event.get("payload") or {}
        kind = event.get("type")
        title = str(event.get("title", "")).strip()
        if kind == "lab_result":
            line = _lab_line(payload, title)
        elif kind == "vitals":
            line = _vitals_line(payload) or title
        elif kind == "med_order":
            line = _order_line(payload, title)
        else:
            line = title
        if line:
            lines.append(line)
            cited.append(event["event_id"])
    for alert in since.get("alerts", []):
        evidence = [item for item in alert.get("evidence_event_ids", []) if item]
        if evidence and alert.get("title"):
            lines.append(f"New alert: {alert['title']}")
            cited.extend(evidence)
    if lines:
        return _claim("; ".join(lines) + ".", list(dict.fromkeys(cited)), [], 0.9)
    if previous:
        return _claim(
            f"No new results, observations or orders since {previous['title']}",
            [previous["event_id"]],
            [],
            0.9,
        )
    return None


def f4_progress(context: dict[str, Any]) -> dict[str, Any]:
    transcript_id = _transcript_event(context)
    analysis = analyse(_segments(context))
    subjective = joined_claim(
        [sentence for sentence in analysis.sentences if sentence.role == "patient"], transcript_id
    )
    objective = _objective(context)
    assessment = [claim(sentence, transcript_id) for sentence in analysis.assessment]
    missing = ["Examination", "Plan"]
    if subjective is None:
        missing.append("Subjective")
    if objective is None:
        missing.append("Objective")
    if not assessment:
        missing.append("Assessment")
    return {
        "subjective": subjective,
        "objective": objective,
        "exam": {"general": None, "systemic": None},
        "assessment": assessment,
        "plan": None,
        "not_documented": missing,
    }


GENERATORS = {"F4": f4_progress}
