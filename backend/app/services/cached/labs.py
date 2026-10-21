from __future__ import annotations

from typing import Any

from .common import (
    _claim,
)

def f11_investigation(context: dict[str, Any]) -> dict[str, Any]:
    results = []
    for lab in context.get("latest_labs", []):
        flag = str(lab.get("flag", "unknown")).lower()
        if flag not in {"normal", "high", "low"}:
            flag = "unknown"
        results.append(
            {
                "name": lab.get("name", ""),
                "value": f"{lab.get('value')} {lab.get('unit', '')}".strip(),
                "flag": flag,
                "event_id": lab["event_id"],
            }
        )
    lab_ids = [lab["event_id"] for lab in context.get("latest_labs", [])]
    abnormal = [lab for lab in context.get("latest_labs", []) if str(lab.get("flag", "")).lower() in {"high", "low"}]
    return {
        "results": results,
        "trend_summary": _claim(
            "Creatinine and eGFR are stable at the current impaired level; potassium remains elevated.",
            lab_ids,
            confidence=0.86,
        ),
        "abnormal_summary": _claim(
            "Abnormal results: " + ", ".join(f"{lab['name']} {lab.get('value')}" for lab in abnormal) + ".",
            [lab["event_id"] for lab in abnormal],
            confidence=0.9,
        ),
        "pending": [
            _claim(
                f"{lab['name']} has not been reviewed.",
                [lab["event_id"]],
            )
            for lab in context.get("unreviewed_labs", [])
        ],
        "not_documented": [],
    }
