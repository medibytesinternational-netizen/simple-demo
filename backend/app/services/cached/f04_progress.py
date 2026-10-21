from __future__ import annotations

from typing import Any

from .common import (
    _claim,
    _segments,
    _seg,
    _transcript_event,
)

def f4_progress(context: dict[str, Any]) -> dict[str, Any]:
    transcript_id = _transcript_event(context)
    vitals = (context.get("vitals") or {}).get("payload", {})
    temp = vitals.get("temperature_c")
    hr = vitals.get("heart_rate")
    objective_bits = []
    if temp is not None:
        objective_bits.append(f"temperature {temp}°C")
    if hr is not None:
        objective_bits.append(f"heart rate {hr} bpm")
    return {
        "subjective": _claim(
            "Patient reports less leg pain overnight and no new breathlessness. Slept poorly.",
            [transcript_id],
            [_seg(context, 1)],
        ),
        "objective": _claim(
            "Overnight observations: " + (", ".join(objective_bits) if objective_bits else "vitals recorded on the timeline") + ".",
            [transcript_id, ((context.get("vitals") or {}).get("event_id") or "")],
            [_seg(context, 2)] if len(_segments(context)) > 1 else [_seg(context, 1)],
        ),
        "exam": {"general": None, "systemic": None},
        "assessment": [
            _claim(
                "Cellulitis — clinically improving on IV antibiotics.",
                [transcript_id],
                [_seg(context, 1)],
                confidence=0.82,
            )
        ],
        "plan": None,
        "not_documented": ["Examination", "Plan"],
    }


GENERATORS = {"F4": f4_progress}
