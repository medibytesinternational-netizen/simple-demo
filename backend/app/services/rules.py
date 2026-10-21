from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Alert, Encounter, Patient, TimelineEvent
from .timeline import add_audit, new_id

PENICILLIN_DRUGS = (
    "amoxicillin",
    "ampicillin",
    "flucloxacillin",
    "piperacillin",
    "penicillin",
    "augmentin",
    "co-amoxiclav",
)

INTERACTION_PAIRS = (
    (("warfarin",), ("ibuprofen", "naproxen", "diclofenac", "aspirin")),
    (("simvastatin",), ("clarithromycin", "erythromycin")),
)


def _active_drugs(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    drugs: dict[str, dict[str, Any]] = {}
    for med in state.get("home_meds", []):
        drugs.setdefault(str(med["drug"]).lower(), med)
    for med in state.get("active_meds", []):
        drugs[str(med["drug"]).lower()] = med
    return drugs


def _add_alert(
    db: Session,
    *,
    patient: Patient,
    encounter: Encounter,
    rule_id: str,
    dedupe_key: str,
    severity: str,
    title: str,
    explanation: str,
    action: str,
    evidence: list[str],
) -> Alert | None:
    existing = db.scalar(select(Alert).where(Alert.dedupe_key == dedupe_key))
    if existing:
        return None
    alert = Alert(
        id=new_id("alr"),
        patient_id=patient.id,
        encounter_id=encounter.id,
        rule_id=rule_id,
        dedupe_key=dedupe_key,
        severity=severity,
        status="open",
        title=title,
        explanation=explanation,
        recommended_action=action,
        evidence_event_ids=evidence,
        created_at=utcnow(),
    )
    db.add(alert)
    add_audit(
        db,
        "alert_created",
        "alert",
        alert.id,
        patient.id,
        actor_type="system",
        actor_name="Rules engine",
        after={"rule_id": rule_id, "severity": severity, "title": title},
        meta={"evidence_event_ids": evidence},
    )
    return alert


def evaluate_rules(db: Session, patient: Patient, encounter: Encounter, state: dict[str, Any]) -> list[Alert]:
    """Deterministic safety rules. No LLM is called here by design."""
    created: list[Alert] = []
    drugs = _active_drugs(state)
    allergies = " ".join(str(a).lower() for a in (patient.allergies or []))
    labs = {str(lab["name"]).lower(): lab for lab in state.get("latest_labs", [])}

    egfr = labs.get("egfr")
    metformin = drugs.get("metformin")
    if egfr and metformin and egfr.get("value") is not None:
        try:
            value = float(egfr["value"])
        except (TypeError, ValueError):
            value = None
        if value is not None and value < 30:
            alert = _add_alert(
                db,
                patient=patient,
                encounter=encounter,
                rule_id="R1",
                dedupe_key=f"R1:metformin:{egfr['event_id']}",
                severity="critical",
                title="Metformin contraindicated at eGFR below 30",
                explanation=(
                    f"Metformin is active while the latest eGFR is {value:g} mL/min/1.73m² "
                    f"({egfr['event_id']}). Risk of lactic acidosis. Review and stop."
                ),
                action="Stop metformin and document the rationale; consider an alternative agent.",
                evidence=[metformin["event_id"], egfr["event_id"]],
            )
            if alert:
                created.append(alert)

    if "penicillin" in allergies:
        for drug_name, med in drugs.items():
            if any(name in drug_name for name in PENICILLIN_DRUGS):
                alert = _add_alert(
                    db,
                    patient=patient,
                    encounter=encounter,
                    rule_id="R2",
                    dedupe_key=f"R2:{drug_name}:{med['event_id']}",
                    severity="critical",
                    title="Penicillin-class order conflicts with documented allergy",
                    explanation=(
                        f"{med['drug']} is a penicillin-class antibiotic. The patient has a "
                        f"documented penicillin allergy ({', '.join(patient.allergies or [])})."
                    ),
                    action="Hold the order and switch to a non-penicillin alternative after review.",
                    evidence=[med["event_id"]],
                )
                if alert:
                    created.append(alert)
                break

    for lab in state.get("unreviewed_labs", []):
        if str(lab.get("flag", "")).lower() in {"high", "low", "critical", "abnormal"}:
            alert = _add_alert(
                db,
                patient=patient,
                encounter=encounter,
                rule_id="R3",
                dedupe_key=f"R3:{lab['event_id']}",
                severity="warning",
                title=f"Unreviewed abnormal result: {lab['name']}",
                explanation=(
                    f"{lab['name']} is {lab.get('value')} {lab.get('unit', '')} "
                    f"(reference {lab.get('reference_range', 'not supplied')}) and has not "
                    f"been reviewed by a clinician."
                ),
                action="Open the investigation review, acknowledge the result, and document the plan.",
                evidence=[lab["event_id"]],
            )
            if alert:
                created.append(alert)

    for left, right in INTERACTION_PAIRS:
        left_drug = next((drugs[name] for name in left if name in drugs), None)
        right_drug = next((drugs[name] for name in right if name in drugs), None)
        if left_drug and right_drug:
            alert = _add_alert(
                db,
                patient=patient,
                encounter=encounter,
                rule_id="R4",
                dedupe_key=f"R4:{left_drug['event_id']}:{right_drug['event_id']}",
                severity="critical",
                title=f"Interacting pair active: {left_drug['drug']} + {right_drug['drug']}",
                explanation=(
                    f"{left_drug['drug']} and {right_drug['drug']} are both active. "
                    "This pair increases bleeding risk, particularly with concurrent renal impairment."
                ),
                action="Review the pair, stop the NSAID where possible, and document the decision.",
                evidence=[left_drug["event_id"], right_drug["event_id"]],
            )
            if alert:
                created.append(alert)

    # R5: a documented note contradicts the patient's recorded allergy state.
    if patient.allergies:
        allergy_event = db.scalar(
            select(TimelineEvent)
            .where(
                TimelineEvent.patient_id == patient.id,
                TimelineEvent.type == "allergy_record",
                TimelineEvent.status == "approved",
            )
            .order_by(TimelineEvent.occurred_at.desc())
        )
        contradictory = db.scalars(
            select(TimelineEvent)
            .where(
                TimelineEvent.patient_id == patient.id,
                TimelineEvent.encounter_id == encounter.id,
                TimelineEvent.type.in_(["admission_note", "progress_note", "nursing_note", "round_note"]),
                TimelineEvent.status == "approved",
            )
            .order_by(TimelineEvent.occurred_at.desc())
        ).all()
        for note in contradictory:
            payload = note.payload or {}
            claims_no_allergy = payload.get("allergies") == [] or payload.get("assertion") == "no_known_allergies"
            if not claims_no_allergy:
                continue
            alert = _add_alert(
                db,
                patient=patient,
                encounter=encounter,
                rule_id="R5",
                dedupe_key=f"R5:{note.id}",
                severity="critical",
                title="Contradicting allergy documentation",
                explanation=(
                    f"{note.title} records no known drug allergies, while the patient record "
                    f"contains: {', '.join(patient.allergies or [])}."
                ),
                action="Reconcile the allergy history with the patient and correct the note.",
                evidence=[note.id, *([allergy_event.id] if allergy_event else [])],
            )
            if alert:
                created.append(alert)
            break

    # R6: a documented plan action remains unresolved against the active order list.
    metformin = drugs.get("metformin")
    if metformin:
        round_notes = db.scalars(
            select(TimelineEvent)
            .where(
                TimelineEvent.patient_id == patient.id,
                TimelineEvent.encounter_id == encounter.id,
                TimelineEvent.type == "round_note",
                TimelineEvent.status == "approved",
            )
            .order_by(TimelineEvent.occurred_at.desc())
        ).all()
        for note in round_notes:
            actions = (note.payload or {}).get("plan_actions", [])
            unresolved = [
                action
                for action in actions
                if str(action.get("drug", "")).lower() == "metformin"
                and str(action.get("status", "open")).lower() == "open"
                and str(action.get("action", "")).lower() in {"hold", "stop", "withhold"}
            ]
            if not unresolved:
                continue
            alert = _add_alert(
                db,
                patient=patient,
                encounter=encounter,
                rule_id="R6",
                dedupe_key=f"R6:metformin:{note.id}",
                severity="warning",
                title="Unresolved plan action: hold metformin",
                explanation=(
                    "The documented round plan says to hold metformin, but metformin remains on "
                    "the active inpatient order list with no documented resolution."
                ),
                action="Resolve the plan action: stop or amend the order and document the decision.",
                evidence=[note.id, metformin["event_id"]],
            )
            if alert:
                created.append(alert)
            break

    if created:
        db.flush()
    return created
