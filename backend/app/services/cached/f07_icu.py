from __future__ import annotations

from typing import Any

from .common import (
    _claim,
    _lab_ids,
)

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
            }
        )
    evidence = list(dict.fromkeys(entry["source_event_id"] for entry in entries if entry["source_event_id"]))
    return {
        "shift_window": context.get("icu_shift_window", {}),
        "summary": _claim(
            f"{len(entries)} structured ICU observations were assembled from device and chart feeds for this shift.",
            evidence[:8],
            confidence=0.9,
        ),
        "entries": entries,
        "not_documented": [] if entries else ["ICU device readings", "Intake/output chart"],
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
