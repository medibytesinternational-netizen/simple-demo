from __future__ import annotations

from typing import Any

from .common import (
    _claim,
    _segments,
    _all_segs,
    _transcript_event,
)

def f3_round(context: dict[str, Any]) -> dict[str, Any]:
    transcript_id = _transcript_event(context)
    segments = _segments(context)
    tasks = []
    instructional = [
        segment
        for segment in segments
        if segment.get("speaker", "").lower() in {"doctor", "clinician", "dr", "dr."}
        and any(
            verb in segment.get("text", "").lower()
            for verb in ("continue", "check", "stop", "increase", "start", "order", "review", "book")
        )
    ]
    if not instructional:
        instructional = [segment for segment in segments if segment.get("speaker", "").lower() in {"doctor", "clinician"}]
    for index, segment in enumerate(instructional):
        text = str(segment.get("text", "")).strip()
        title = text.rstrip(".")
        priority = "urgent" if any(word in text.lower() for word in ("stop", "potassium", "renal", "check")) else "routine"
        tasks.append(
            {
                "title": title[:110],
                "detail": f"From round discussion: {text}",
                "priority": priority,
                "due_in_hours": 8 if index == 1 else 24,
                "source_segment_ids": [segment["segment_id"]],
                "confidence": 0.9 if index < 3 else 0.62,
            }
        )
    return {
        "note_claims": [
            _claim(
                "Ward round reviewed the right lower leg cellulitis, renal function and medication safety.",
                [transcript_id],
                _all_segs(context)[:2],
            ),
            _claim(
                "Continue IV antibiotics and review the leg tomorrow. Check potassium and renal function. Hold metformin until renal function improves.",
                [transcript_id],
                _all_segs(context)[:4],
            ),
            _claim(
                "The suggestion to increase ibuprofen was not accepted because of CKD and concurrent warfarin.",
                [transcript_id],
                _all_segs(context)[-1:],
                0.65,
            ),
        ],
        "nursing_entries": [
            _claim(
                "Continue IV flucloxacillin as prescribed; review the right leg at the next ward round.",
                [transcript_id],
                _all_segs(context)[:1],
            ),
            _claim(
                "Check potassium and renal function this morning and escalate abnormal results.",
                [transcript_id],
                _all_segs(context)[1:2],
            ),
            _claim(
                "Hold metformin until renal function is reviewed.",
                [transcript_id],
                _all_segs(context)[2:3],
            ),
        ],
        "proposed_tasks": tasks,
        "not_documented": [],
    }


GENERATORS = {"F3": f3_round}
