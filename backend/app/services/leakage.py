from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import Encounter, Patient


from .claims import claim_prep


def leakage(db: Session, patient: Patient, encounter: Encounter, state: dict[str, Any]) -> dict[str, Any]:
    prep = claim_prep(db, patient, encounter, state)
    findings = []
    for item in prep["unbilled_procedures"]:
        findings.append(
            {
                "id": f"leak_{item['event_id']}",
                "procedure": item["procedure"],
                "billing_status": "unbilled",
                "explanation": "Documented procedure is absent from the seeded bill.",
                "evidence_event_ids": item["evidence_event_ids"],
            }
        )
    for item in prep.get("underbilled_items", []):
        findings.append(
            {
                "id": f"underbilled_{item['id']}",
                "procedure": item["description"],
                "billing_status": "underbilled",
                "explanation": (
                    f"Seeded expected amount INR {item['expected_amount']:,.0f} exceeds the billed "
                    f"INR {item['billed_amount']:,.0f} by INR {item['variance']:,.0f}."
                ),
                "evidence_event_ids": item["evidence_event_ids"],
            }
        )
    for item in prep["unsupported_items"]:
        findings.append(
            {
                "id": f"unsupported_{item['id']}",
                "procedure": item["description"],
                "billing_status": "unsupported",
                "explanation": "Billed item has no supporting documentation event.",
                "evidence_event_ids": item["evidence_event_ids"],
            }
        )
    return {
        "findings": findings,
        "count": len(findings),
        "summary": f"{len(findings)} documentation-to-billing gaps found by deterministic comparison.",
    }
