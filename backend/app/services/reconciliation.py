"""Medication reconciliation (F6): home list against the current plan, deterministic.

Every value in a discrepancy is computed from the record. Decisions made by clinicians
(see ``services/medicines.py``) are merged in as ``status`` open or resolved.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# The same two pairs the safety rules use. Kept here as a fallback so this module still works
# if the rules module renames its list; a test checks the two lists agree.
LOCAL_INTERACTION_PAIRS = (
    (("warfarin",), ("ibuprofen", "naproxen", "diclofenac", "aspirin")),
    (("simvastatin",), ("clarithromycin", "erythromycin")),
)
try:
    from .rules import INTERACTION_PAIRS
except ImportError:  # pragma: no cover
    INTERACTION_PAIRS = LOCAL_INTERACTION_PAIRS

# The safety rule for metformin (R1) uses the same threshold.
METFORMIN_EGFR_LIMIT = 30


def _lab(state: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next(
        (lab for lab in state.get("latest_labs", []) if str(lab["name"]).lower() == name.lower()),
        None,
    )


def _med_label(med: dict[str, Any]) -> str:
    return " ".join(
        str(med.get(key, "")).strip()
        for key in ("drug", "dose", "route", "frequency")
        if str(med.get(key, "")).strip()
    )


def _same(left: str, right: str) -> bool:
    """Case and spacing do not make two values different ("1 g" and "1g")."""
    return "".join(left.lower().split()) == "".join(right.lower().split())


def fingerprint(item: dict[str, Any]) -> str:
    """What a decision was made on: the same kind, values and evidence."""
    basis = [
        item.get("kind", ""),
        item.get("home_value", ""),
        item.get("current_value", ""),
        sorted(item.get("evidence_event_ids", [])),
    ]
    return hashlib.sha1(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:16]


def _slug(text: str) -> str:
    return "_".join(str(text).lower().split())


def _merge_decision(item: dict[str, Any], decisions: dict[str, dict[str, Any]]) -> None:
    latest = decisions.get(item["id"])
    item["status"] = "open"
    item["decision"] = None
    item["note"] = None
    item["decided_by"] = None
    item["decided_at"] = None
    item["earlier_decision"] = None
    if not latest:
        return
    if latest.get("fingerprint") == item["fingerprint"]:
        item["status"] = "resolved"
        item["decision"] = latest["decision"]
        item["note"] = latest.get("note")
        item["decided_by"] = latest.get("decided_by")
        item["decided_at"] = latest.get("decided_at")
    else:
        # The record changed after the decision, so a clinician must look again.
        item["earlier_decision"] = {
            "decision": latest["decision"],
            "decided_by": latest.get("decided_by"),
            "decided_at": latest.get("decided_at"),
        }


def reconciliation(state: dict[str, Any], decisions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    home = state.get("home_meds", [])
    current = state.get("active_meds", [])
    current_by_drug: dict[str, dict[str, Any]] = {}
    for med in current:
        current_by_drug[str(med["drug"]).lower()] = med
    home_by_drug = {str(med["drug"]).lower(): med for med in home}
    discrepancies: list[dict[str, Any]] = []
    egfr = _lab(state, "eGFR")
    latest_decisions: dict[str, dict[str, Any]] = {}
    for decision in decisions or []:  # oldest first, so the newest wins
        latest_decisions[decision["discrepancy_id"]] = decision

    def add(
        *,
        ident: str,
        kind: str,
        drug: str,
        home_med: str,
        current_order: str | None,
        explanation: str,
        evidence: list[str],
        field: str = "",
        home_value: str = "",
        current_value: str = "",
        recommended_action: str = "Review and document the reconciliation decision.",
    ) -> None:
        item = {
            "id": ident,
            "kind": kind,
            "drug": drug,
            "home_med": home_med,
            "current_order": current_order,
            "field": field,
            "home_value": home_value,
            "current_value": current_value,
            "explanation": explanation,
            "recommended_action": recommended_action,
            "evidence_event_ids": [event_id for event_id in evidence if event_id],
        }
        item["fingerprint"] = fingerprint(item)
        _merge_decision(item, latest_decisions)
        discrepancies.append(item)

    metformin = current_by_drug.get("metformin")
    if metformin and egfr:
        try:
            egfr_value = float(egfr["value"])
        except (TypeError, ValueError):
            egfr_value = None
        if egfr_value is not None and egfr_value < METFORMIN_EGFR_LIMIT:
            home_metformin = home_by_drug.get("metformin")
            unit = str(egfr.get("unit", "") or "").strip()
            egfr_text = f"eGFR {egfr_value:g}" + (f" {unit}" if unit else "")
            add(
                ident="disc_metformin",
                kind="contraindicated",
                drug=metformin["drug"],
                home_med=_med_label(home_metformin) if home_metformin else "Not on the home list",
                current_order=_med_label(metformin),
                explanation=(
                    f"{metformin['drug']} is active while {egfr_text}, below the safety limit of "
                    f"{METFORMIN_EGFR_LIMIT}. A prescriber should review it."
                ),
                evidence=[metformin["event_id"], egfr["event_id"]],
                field="renal safety",
                home_value=egfr_text,
                current_value=f"{metformin['drug']} active",
                recommended_action=f"Review whether {metformin['drug']} should continue and document the reason.",
            )

    for drug, med in home_by_drug.items():
        current_med = current_by_drug.get(drug)
        if not current_med:
            add(
                ident=f"disc_omitted_{_slug(drug)}",
                kind="omitted",
                drug=med["drug"],
                home_med=_med_label(med),
                current_order=None,
                explanation="Home medication is not present on the current inpatient order list.",
                evidence=[med["event_id"]],
                field="presence",
                home_value="Active at home",
                current_value="Not ordered",
                recommended_action="Confirm whether the medicine should be continued, held or stopped.",
            )
            continue

        for field, kind in (
            ("dose", "dose_changed"),
            ("route", "route_changed"),
            ("frequency", "frequency_changed"),
            ("indication", "indication_missing"),
        ):
            home_value = str(med.get(field, "") or "").strip()
            current_value = str(current_med.get(field, "") or "").strip()
            if not home_value:
                continue
            if field == "indication" and not current_value:
                add(
                    ident=f"disc_indication_{_slug(drug)}",
                    kind=kind,
                    drug=med["drug"],
                    home_med=_med_label(med),
                    current_order=_med_label(current_med),
                    explanation="The current inpatient order has no documented indication.",
                    evidence=[med["event_id"], current_med["event_id"]],
                    field=field,
                    home_value=home_value,
                    current_value="Not documented",
                    recommended_action="Document the indication for the current order.",
                )
            elif current_value and not _same(home_value, current_value):
                add(
                    ident=f"disc_{field}_{_slug(drug)}",
                    kind=kind,
                    drug=med["drug"],
                    home_med=_med_label(med),
                    current_order=_med_label(current_med),
                    explanation=f"The {field} differs between the home list and the current inpatient order.",
                    evidence=[med["event_id"], current_med["event_id"]],
                    field=field,
                    home_value=home_value,
                    current_value=current_value,
                    recommended_action=f"Confirm the intended {field} with the prescriber.",
                )

    # Interacting pairs: drugs on the current order list, or on the home list when not ordered.
    on_list: dict[str, dict[str, Any]] = {}
    for med in home:
        on_list.setdefault(str(med["drug"]).lower(), med)
    on_list.update(current_by_drug)
    for left, right in INTERACTION_PAIRS:
        left_name = next((name for name in left if name in on_list), None)
        right_name = next((name for name in right if name in on_list), None)
        if not left_name or not right_name:
            continue
        left_med, right_med = on_list[left_name], on_list[right_name]
        add(
            ident=f"disc_{_slug(left_name)}_{_slug(right_name)}",
            kind="interaction",
            drug=right_med["drug"],
            home_med=f"{left_med['drug']} + {right_med['drug']}",
            current_order="; ".join(_med_label(m) for m in (left_med, right_med)),
            explanation=(
                f"{left_med['drug']} and {right_med['drug']} are both on the medication list. "
                "The safety rules flag this pair as an interaction."
            ),
            evidence=[left_med["event_id"], right_med["event_id"]],
            field="interaction",
            home_value=f"{left_med['drug']} active",
            current_value=f"{right_med['drug']} active",
            recommended_action=f"Review the pair and document the decision for {right_med['drug']}.",
        )

    open_items = [item for item in discrepancies if item["status"] == "open"]
    return {
        "discrepancies": discrepancies,
        "home_medications": home,
        "current_medications": current,
        "unresolved_count": len(open_items),
        "summary": (
            f"{len(discrepancies)} discrepancies found by deterministic comparison; "
            f"{len(open_items)} still open."
        ),
    }
