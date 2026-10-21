from __future__ import annotations

from typing import Any

def f13_leakage(context: dict[str, Any]) -> dict[str, Any]:
    revenue = context.get("revenue", {}) or {}
    findings = [
        {
            "procedure": item.get("procedure", "Revenue finding"),
            "billing_status": item.get("billing_status", "unsupported"),
            "explanation": item.get("explanation", "Review required."),
            "evidence_event_ids": item.get("evidence_event_ids", []),
        }
        for item in revenue.get("findings", [])
    ]
    return {
        "summary": (
            f"{len(findings)} revenue findings require review. Amounts are computed from the seeded bill; "
            "nothing is charged or submitted automatically."
        ),
        "findings": findings,
    }


GENERATORS = {"F13": f13_leakage}
