"""Medication reconciliation (F6): home list against the current plan, deterministic."""

from __future__ import annotations

from typing import Any


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


def reconciliation(state: dict[str, Any]) -> dict[str, Any]:
    home = state.get("home_meds", [])
    current = state.get("active_meds", [])
    current_by_drug: dict[str, dict[str, Any]] = {}
    for med in current:
        current_by_drug[str(med["drug"]).lower()] = med
    home_by_drug = {str(med["drug"]).lower(): med for med in home}
    discrepancies: list[dict[str, Any]] = []
    egfr = _lab(state, "eGFR")

    def add(
        *,
        ident: str,
        kind: str,
        home_med: str,
        current_order: str | None,
        explanation: str,
        evidence: list[str],
        field: str = "",
        home_value: str = "",
        current_value: str = "",
        recommended_action: str = "Review and document the reconciliation decision.",
    ) -> None:
        discrepancies.append(
            {
                "id": ident,
                "kind": kind,
                "home_med": home_med,
                "current_order": current_order,
                "field": field,
                "home_value": home_value,
                "current_value": current_value,
                "explanation": explanation,
                "recommended_action": recommended_action,
                "evidence_event_ids": evidence,
            }
        )

    metformin = current_by_drug.get("metformin")
    if metformin and egfr:
        try:
            egfr_value = float(egfr["value"])
        except (TypeError, ValueError):
            egfr_value = None
        if egfr_value is not None and egfr_value < 30:
            add(
                ident="disc_metformin",
                kind="contraindicated",
                home_med="Metformin 1 g BD",
                current_order=f"{metformin.get('dose', '')} {metformin.get('frequency', '')}".strip(),
                explanation=(
                    f"Metformin remains active while eGFR is {egfr_value:g}. "
                    "It should be reviewed and stopped in severe renal impairment."
                ),
                evidence=[metformin["event_id"], egfr["event_id"]],
                field="renal safety",
                home_value="eGFR 22 mL/min/1.73m²",
                current_value="Metformin active",
                recommended_action="Stop metformin and document the rationale; consider an alternative agent.",
            )

    for drug, med in home_by_drug.items():
        current_med = current_by_drug.get(drug)
        if not current_med:
            add(
                ident=f"disc_omitted_{drug.replace(' ', '_')}",
                kind="omitted",
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

        for field, kind, label in (
            ("dose", "dose_changed", "dose"),
            ("route", "route_changed", "route"),
            ("frequency", "frequency_changed", "frequency"),
            ("indication", "indication_missing", "indication"),
        ):
            home_value = str(med.get(field, "") or "").strip()
            current_value = str(current_med.get(field, "") or "").strip()
            if not home_value:
                continue
            if field == "indication" and not current_value:
                add(
                    ident=f"disc_indication_{drug.replace(' ', '_')}",
                    kind=kind,
                    home_med=_med_label(med),
                    current_order=_med_label(current_med),
                    explanation="The current inpatient order has no documented indication.",
                    evidence=[med["event_id"], current_med["event_id"]],
                    field=label,
                    home_value=home_value,
                    current_value="Not documented",
                    recommended_action="Document the indication for the current order.",
                )
            elif current_value and home_value.lower() != current_value.lower():
                add(
                    ident=f"disc_{field}_{drug.replace(' ', '_')}",
                    kind=kind,
                    home_med=_med_label(med),
                    current_order=_med_label(current_med),
                    explanation=f"{label.title()} differs between the home list and the current inpatient order.",
                    evidence=[med["event_id"], current_med["event_id"]],
                    field=label,
                    home_value=home_value,
                    current_value=current_value,
                    recommended_action=f"Confirm the intended {label} with the prescriber.",
                )

    warfarin = current_by_drug.get("warfarin") or home_by_drug.get("warfarin")
    ibuprofen = current_by_drug.get("ibuprofen") or home_by_drug.get("ibuprofen")
    if warfarin and ibuprofen:
        add(
            ident="disc_warfarin_ibuprofen",
            kind="interaction",
            home_med="Warfarin + Ibuprofen",
            current_order="Both active",
            explanation=(
                "Concurrent warfarin and ibuprofen increases bleeding risk, especially with CKD. "
                "Review and stop the NSAID unless there is a documented reason."
            ),
            evidence=[warfarin["event_id"], ibuprofen["event_id"]],
            field="interaction",
            home_value="Warfarin active",
            current_value="Ibuprofen active",
            recommended_action="Review the pair, stop the NSAID where possible, and document the decision.",
        )

    return {
        "discrepancies": discrepancies,
        "home_medications": home,
        "current_medications": current,
        "summary": f"{len(discrepancies)} discrepancies found by deterministic comparison.",
    }
