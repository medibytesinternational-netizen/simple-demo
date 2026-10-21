from __future__ import annotations

from typing import Any

def f12_claim(context: dict[str, Any]) -> dict[str, Any]:
    revenue = context.get("revenue", {}) or {}
    gaps = []
    for item in revenue.get("missing_documents", []):
        gaps.append(
            {
                "kind": "missing_document",
                "description": f"{item.get('label')} is required before review.",
                "evidence_event_ids": item.get("evidence_event_ids", []),
            }
        )
    for item in revenue.get("unbilled_procedures", []):
        gaps.append(
            {
                "kind": "unbilled_procedure",
                "description": f"{item.get('procedure')} is documented but not billed.",
                "evidence_event_ids": item.get("evidence_event_ids", []),
            }
        )
    for item in revenue.get("underbilled_items", []):
        gaps.append(
            {
                "kind": "underbilled_item",
                "description": (
                    f"{item.get('description')} is billed at INR {item.get('billed_amount', 0):,.0f} "
                    f"against an expected INR {item.get('expected_amount', 0):,.0f}."
                ),
                "evidence_event_ids": item.get("evidence_event_ids", []),
            }
        )
    for item in revenue.get("contradictions", []):
        gaps.append(
            {
                "kind": "contradiction",
                "description": f"{item.get('title')}: {item.get('explanation')}",
                "evidence_event_ids": item.get("evidence_event_ids", []),
            }
        )
    if revenue.get("tpa_review", {}).get("status") == "needs_clarification":
        gaps.append(
            {
                "kind": "tpa_clarification",
                "description": "TPA review is blocked until the contradictions are resolved by a human.",
                "evidence_event_ids": revenue.get("tpa_review", {}).get("evidence_event_ids", []),
            }
        )
    for item in revenue.get("unsupported_items", []):
        gaps.append(
            {
                "kind": "unsupported_billing",
                "description": f"{item.get('description')} is billed without supporting documentation.",
                "evidence_event_ids": item.get("evidence_event_ids", []),
            }
        )
    return {
        "summary": (
            f"Claim pack has {len(gaps)} review gaps. The pack is assembled for human review only; "
            "it is not submitted and no charge is raised."
        ),
        "gaps": gaps,
    }


GENERATORS = {"F12": f12_claim}
