from __future__ import annotations

from typing import Any

def f6_recon(context: dict[str, Any]) -> dict[str, Any]:
    extra = (context.get("reconciliation") or {})
    discrepancies = extra.get("discrepancies", [])
    return {
        "summary": (
            f"{len(discrepancies)} medication reconciliation discrepancies require clinician review. "
            "The comparison is deterministic; this text only explains the findings."
        ),
        "discrepancies": [
            {
                "home_med": item.get("home_med", ""),
                "current_order": item.get("current_order"),
                "kind": item.get("kind", "omitted"),
                "explanation": item.get("explanation", "Review required."),
                "evidence_event_ids": item.get("evidence_event_ids", []),
            }
            for item in discrepancies
        ],
    }


GENERATORS = {"F6": f6_recon}
