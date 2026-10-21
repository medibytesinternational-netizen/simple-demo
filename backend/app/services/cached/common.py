"""Helpers shared by the cached draft generators."""

from __future__ import annotations

from typing import Any

def _claim(
    text: str,
    event_ids: list[str] | None = None,
    segment_ids: list[str] | None = None,
    confidence: float = 0.92,
) -> dict[str, Any]:
    return {
        "text": text,
        "source_event_ids": [item for item in (event_ids or []) if item],
        "source_segment_ids": [item for item in (segment_ids or []) if item],
        "confidence": confidence,
    }


def _segments(context: dict[str, Any]) -> list[dict[str, Any]]:
    return (context.get("transcript") or {}).get("segments", [])


def _seg(context: dict[str, Any], index: int) -> str:
    segments = _segments(context)
    if not segments:
        return ""
    if index <= len(segments):
        return segments[index - 1]["segment_id"]
    return segments[0]["segment_id"]


def _all_segs(context: dict[str, Any]) -> list[str]:
    return [segment["segment_id"] for segment in _segments(context)]


def _transcript_event(context: dict[str, Any]) -> str:
    return (context.get("transcript") or {}).get("event_id", "")


def _events(context: dict[str, Any], type_name: str) -> list[dict[str, Any]]:
    return [event for event in context.get("evidence_events", []) if event.get("type") == type_name]


def _first(context: dict[str, Any], type_name: str) -> dict[str, Any] | None:
    return next(iter(_events(context, type_name)), None)


def _lab(context: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next(
        (lab for lab in context.get("latest_labs", []) if str(lab.get("name", "")).lower() == name.lower()),
        None,
    )


def _lab_ids(context: dict[str, Any], names: list[str]) -> list[str]:
    ids = []
    for name in names:
        lab = _lab(context, name)
        if lab:
            ids.append(lab["event_id"])
    return ids


def _patient(context: dict[str, Any]) -> dict[str, Any]:
    return context.get("patient", {})


def _active_meds(context: dict[str, Any]) -> list[dict[str, Any]]:
    return context.get("active_medications", [])


def _home_meds(context: dict[str, Any]) -> list[dict[str, Any]]:
    return context.get("home_medications", [])
