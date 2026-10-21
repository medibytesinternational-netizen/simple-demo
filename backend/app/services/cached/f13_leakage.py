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
    kinds: dict[str, int] = {}
    for item in revenue.get("findings", []):
        kind = item.get("kind") or item.get("billing_status", "unsupported")
        kinds[kind] = kinds.get(kind, 0) + 1
    breakdown = ", ".join(f"{count} {kind.replace('_', ' ')}" for kind, count in kinds.items())
    amount = revenue.get("leakage_amount")
    summary = f"{len(findings)} revenue findings require review"
    if breakdown:
        summary += f" ({breakdown})"
    summary += ". Amounts are computed from the tariff"
    if amount:
        summary += f"; potential uncharged value INR {amount:,.0f}"
    summary += ". Nothing is charged or submitted automatically."
    return {"summary": summary, "findings": findings}


GENERATORS = {"F13": f13_leakage}
