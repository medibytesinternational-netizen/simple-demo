from __future__ import annotations

from typing import Any

from .common import (
    _claim,
    _lab_ids,
)

ICU_CHART_CATEGORIES = ("ventilator", "infusion", "neuro", "lines")
WARD_CHART_CATEGORIES = ("vitals", "intake_output", "skin", "medication")
ALL_CATEGORIES = ICU_CHART_CATEGORIES + WARD_CHART_CATEGORIES
CATEGORY_NAMES = {
    "vitals": "Vital signs",
    "ventilator": "Ventilator readings",
    "infusion": "Infusions",
    "intake_output": "Intake and output",
    "neuro": "Neuro observations",
    "lines": "Lines and drains",
    "skin": "Skin and pressure care",
    "medication": "Medication administrations",
}


def chart_for(category: str, ward: str | None) -> str:
    """The chart a category belongs to; every category goes to the ICU chart on an ICU ward."""
    if "icu" in (ward or "").lower():
        return "icu"
    return "ward" if category in WARD_CHART_CATEGORIES else "icu"


def _entry(event: Any, ward: str | None) -> dict[str, Any]:
    payload = event.payload or {}
    category = payload.get("category", "other")
    chart = payload.get("chart") if payload.get("chart") in ("icu", "ward") else chart_for(category, ward)
    return {
        "category": category,
        "label": payload.get("label", event.title),
        "value": str(payload.get("value", "")),
        "unit": payload.get("unit", ""),
        "recorded_at": payload.get("recorded_at", event.occurred_at.isoformat()),
        "device": payload.get("device", ""),
        "source_event_id": event.id,
        "confidence": event.confidence or 0.95,
        "chart": chart,
    }


def _medication_entry(event: Any, ward: str | None) -> dict[str, Any]:
    payload = event.payload or {}
    value = f"{payload.get('dose', '')} {payload.get('status', '')}".strip()
    return {
        "category": "medication",
        "label": payload.get("drug") or event.title,
        "value": value,
        "unit": "",
        "recorded_at": payload.get("given_at") or event.occurred_at.isoformat(),
        "device": "",
        "source_event_id": event.id,
        "confidence": event.confidence or 0.95,
        "chart": chart_for("medication", ward),
    }


def assemble_entries(events: list[Any], ward: str | None, chart: str | None = None) -> list[dict[str, Any]]:
    """Device readings and administrations of one encounter as sheet entries, oldest first."""
    entries = []
    for event in events:
        if event.type == "device_reading":
            entries.append(_entry(event, ward))
        elif event.type == "medication_administration":
            entries.append(_medication_entry(event, ward))
    if chart:
        entries = [entry for entry in entries if entry["chart"] == chart]
    entries.sort(key=lambda item: str(item.get("recorded_at", "")))
    return entries


def shift_window(entries: list[dict[str, Any]]) -> dict[str, str]:
    return {
        "start": entries[0]["recorded_at"] if entries else "",
        "end": entries[-1]["recorded_at"] if entries else "",
    }


def missing_categories(entries: list[dict[str, Any]], ward: str | None, chart: str | None = None) -> list[str]:
    """Categories in scope that have no entry. Derived from the entries, never fixed text."""
    present = {entry["category"] for entry in entries}
    return [
        CATEGORY_NAMES[category]
        for category in ALL_CATEGORIES
        if (not chart or chart_for(category, ward) == chart) and category not in present
    ]


def f7_icu_flow_sheet(context: dict[str, Any]) -> dict[str, Any]:
    entries = []
    for item in context.get("icu_entries", [])[:80]:
        entries.append(
            {
                "category": item.get("category", "other"),
                "label": item.get("label", ""),
                "value": str(item.get("value", "")),
                "unit": item.get("unit", ""),
                "recorded_at": item.get("recorded_at", ""),
                "device": item.get("device", ""),
                "source_event_id": item.get("source_event_id", ""),
                "confidence": float(item.get("confidence", 0.95)),
                "chart": item.get("chart", "icu"),
            }
        )
    evidence = list(dict.fromkeys(entry["source_event_id"] for entry in entries if entry["source_event_id"]))
    ward = (context.get("encounter") or {}).get("ward")
    missing = context.get("icu_missing")
    if missing is None:
        missing = missing_categories(entries, ward, context.get("icu_chart"))
    if entries:
        text = f"{len(entries)} structured observations were assembled from device feeds and recorded administrations."
    else:
        text = "No device readings or administrations are recorded for this encounter."
    return {
        "shift_window": context.get("icu_shift_window") or shift_window(entries),
        "summary": _claim(text, evidence[:8], confidence=0.9),
        "entries": entries,
        "not_documented": list(missing),
    }


def f7_nursing(context: dict[str, Any]) -> dict[str, Any]:
    vitals = (context.get("vitals") or {}).get("payload", {})
    vitals_id = (context.get("vitals") or {}).get("event_id", "")
    labs = _lab_ids(context, ["Creatinine", "eGFR", "Potassium", "WBC"])
    return {
        "shift_window": {"start": "2026-10-19T20:00:00", "end": "2026-10-20T08:00:00"},
        "vitals_summary": _claim(
            f"Afebrile overnight with temperature {vitals.get('temperature_c', 'not recorded')}°C, "
            f"heart rate {vitals.get('heart_rate', 'not recorded')} bpm and SpO2 {vitals.get('spo2', 'not recorded')}% on room air.",
            [vitals_id],
            confidence=0.9,
        ),
        "meds_administered": [],
        "incidents": [
            _claim(
                "No falls, no new confusion and no escalation required overnight.",
                [vitals_id],
                confidence=0.86,
            )
        ],
        "concerns": [
            _claim(
                "Renal function remains impaired and potassium is elevated; the day team should review.",
                labs,
                confidence=0.9,
            )
        ],
        "not_documented": ["Medication administration record", "Intake/output chart"],
    }


GENERATORS = {"F7": f7_icu_flow_sheet}
