"""F6 draft without an AI key: the comparison already made, laid out line by line.

Nothing is written here that is not in the reconciliation result (which is computed from the
record), and every line keeps the ids of the events it came from.
"""

from __future__ import annotations

from typing import Any


def f6_recon(context: dict[str, Any]) -> dict[str, Any]:
    extra = context.get("reconciliation") or {}
    discrepancies = extra.get("discrepancies", [])
    open_count = sum(1 for item in discrepancies if item.get("status", "open") == "open")
    if discrepancies:
        noun = "difference" if len(discrepancies) == 1 else "differences"
        summary = (
            f"{len(discrepancies)} medication {noun} found between the home list and the current orders; "
            f"{open_count} still need a clinician decision."
        )
    else:
        summary = "No differences found between the home list and the current orders."
    return {
        "summary": summary,
        "discrepancies": [
            {
                "home_med": item.get("home_med", ""),
                "current_order": item.get("current_order"),
                "kind": item.get("kind", "omitted"),
                "field": item.get("field", ""),
                "home_value": item.get("home_value", ""),
                "current_value": item.get("current_value", ""),
                "explanation": item.get("explanation", ""),
                "recommended_action": item.get("recommended_action", ""),
                "evidence_event_ids": item.get("evidence_event_ids", []),
            }
            for item in discrepancies
        ],
    }


GENERATORS = {"F6": f6_recon}
