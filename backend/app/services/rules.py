from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Alert, Encounter, Patient, TimelineEvent
from .claims import HOLD_VERBS, NEGATION_BEFORE_RE, _sentences
from .timeline import add_audit, new_id

# Deterministic rules only. Nothing in this module calls a model.

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

# Notes that can contradict the recorded allergy state.
ALLERGY_NOTE_TYPES = ["admission_note", "progress_note", "nursing_note", "round_note", "consult_note"]

KEY_PREFIX = "rule:"


@dataclass
class Finding:
    rule_id: str
    key: str
    severity: str
    title: str
    explanation: str
    action: str
    evidence: list[str] = field(default_factory=list)


def _active_drugs(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    drugs: dict[str, dict[str, Any]] = {}
    for med in state.get("home_meds", []):
        drugs.setdefault(str(med["drug"]).lower(), med)
    for med in state.get("active_meds", []):
        drugs[str(med["drug"]).lower()] = med
    return drugs


def _ordered_drugs(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Inpatient and discharge orders only. A home medicine is not an order."""
    return {str(med["drug"]).lower(): med for med in state.get("active_meds", [])}


def _find_row(db: Session, patient: Patient, key: str) -> Alert | None:
    return db.scalar(
        select(Alert).where(
            Alert.patient_id == patient.id,
            Alert.dedupe_key.in_([key, f"{key}@{patient.id}"]),
        )
    )


def _new_key(db: Session, patient: Patient, key: str) -> str:
    # dedupe_key is unique across the whole table; a second patient gets a suffixed key.
    taken = db.scalar(select(Alert.id).where(Alert.dedupe_key == key))
    return f"{key}@{patient.id}" if taken else key


def _apply(db: Session, patient: Patient, encounter: Encounter, finding: Finding, produced: set[str]) -> Alert | None:
    """Create, update in place or reopen the alert for one finding. Returns it only when created or reopened."""
    row = _find_row(db, patient, finding.key)
    evidence = list(dict.fromkeys(finding.evidence))
    if row is None:
        alert = Alert(
            id=new_id("alr"),
            patient_id=patient.id,
            encounter_id=encounter.id,
            rule_id=finding.rule_id,
            dedupe_key=_new_key(db, patient, finding.key),
            severity=finding.severity,
            status="open",
            title=finding.title,
            explanation=finding.explanation,
            recommended_action=finding.action,
            evidence_event_ids=evidence,
            created_at=utcnow(),
        )
        db.add(alert)
        db.flush()
        produced.add(alert.dedupe_key)
        add_audit(
            db,
            "alert_created",
            "alert",
            alert.id,
            patient.id,
            actor_type="system",
            actor_name="Rules engine",
            after={"rule_id": finding.rule_id, "severity": finding.severity, "title": finding.title},
            meta={"evidence_event_ids": evidence},
        )
        return alert

    produced.add(row.dedupe_key)
    changed = set(row.evidence_event_ids or []) != set(evidence)
    if row.status != "open" and not changed:
        return None

    before = list(row.evidence_event_ids or [])
    reopened = row.status != "open"
    row.encounter_id = encounter.id
    row.rule_id = finding.rule_id
    row.severity = finding.severity
    row.title = finding.title
    row.explanation = finding.explanation
    row.recommended_action = finding.action
    row.evidence_event_ids = evidence
    if reopened:
        previous = row.status
        row.status = "open"
        row.resolved_at = None
        row.resolution = None
        add_audit(
            db,
            "alert_reopened",
            "alert",
            row.id,
            patient.id,
            actor_type="system",
            actor_name="Rules engine",
            before={"status": previous, "evidence_event_ids": before},
            after={"status": "open", "evidence_event_ids": evidence},
        )
        return row
    if changed:
        add_audit(
            db,
            "alert_updated",
            "alert",
            row.id,
            patient.id,
            actor_type="system",
            actor_name="Rules engine",
            before={"evidence_event_ids": before},
            after={"evidence_event_ids": evidence},
        )
    return None


def _findings(db: Session, patient: Patient, encounter: Encounter, state: dict[str, Any]) -> list[Finding]:
    found: list[Finding] = []
    drugs = _active_drugs(state)
    ordered = _ordered_drugs(state)
    allergies = " ".join(str(a).lower() for a in (patient.allergies or []))
    labs = {str(lab["name"]).lower(): lab for lab in state.get("latest_labs", [])}

    # R1: metformin ordered while eGFR is below 30.
    egfr = labs.get("egfr")
    metformin = ordered.get("metformin")
    if egfr and metformin and egfr.get("value") is not None:
        try:
            value = float(egfr["value"])
        except (TypeError, ValueError):
            value = None
        if value is not None and value < 30:
            found.append(
                Finding(
                    "R1",
                    "rule:R1:metformin",
                    "critical",
                    "Metformin contraindicated at eGFR below 30",
                    f"Metformin is active while the latest eGFR is {value:g} mL/min/1.73m² "
                    f"({egfr['event_id']}). Risk of lactic acidosis. Review and stop.",
                    "Stop metformin and document the rationale; consider an alternative agent.",
                    [metformin["event_id"], egfr["event_id"]],
                )
            )

    # R2: penicillin-class drug with a documented penicillin allergy.
    if "penicillin" in allergies:
        for drug_name, med in drugs.items():
            if any(name in drug_name for name in PENICILLIN_DRUGS):
                found.append(
                    Finding(
                        "R2",
                        f"rule:R2:{drug_name}",
                        "critical",
                        "Penicillin-class order conflicts with documented allergy",
                        f"{med['drug']} is a penicillin-class antibiotic. The patient has a "
                        f"documented penicillin allergy ({', '.join(patient.allergies or [])}).",
                        "Hold the order and switch to a non-penicillin alternative after review.",
                        [med["event_id"]],
                    )
                )

    # R3: abnormal result nobody has reviewed. One alert per lab name.
    for lab in state.get("unreviewed_labs", []):
        if str(lab.get("flag", "")).lower() in {"high", "low", "critical", "abnormal"}:
            found.append(
                Finding(
                    "R3",
                    f"rule:R3:{str(lab['name']).lower()}",
                    "warning",
                    f"Unreviewed abnormal result: {lab['name']}",
                    f"{lab['name']} is {lab.get('value')} {lab.get('unit', '')} "
                    f"(reference {lab.get('reference_range', 'not supplied')}) and has not "
                    f"been reviewed by a clinician.",
                    "Open the investigation review, acknowledge the result, and document the plan.",
                    [lab["event_id"]],
                )
            )

    # R4: interacting pair active.
    for left, right in INTERACTION_PAIRS:
        left_name = next((name for name in left if name in drugs), None)
        right_name = next((name for name in right if name in drugs), None)
        if left_name and right_name:
            left_drug, right_drug = drugs[left_name], drugs[right_name]
            found.append(
                Finding(
                    "R4",
                    f"rule:R4:{left_name}+{right_name}",
                    "critical",
                    f"Interacting pair active: {left_drug['drug']} + {right_drug['drug']}",
                    f"{left_drug['drug']} and {right_drug['drug']} are both active. "
                    "This pair increases bleeding risk, particularly with concurrent renal impairment.",
                    "Review the pair, stop the NSAID where possible, and document the decision.",
                    [left_drug["event_id"], right_drug["event_id"]],
                )
            )

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
        notes = db.scalars(
            select(TimelineEvent)
            .where(
                TimelineEvent.patient_id == patient.id,
                TimelineEvent.encounter_id == encounter.id,
                TimelineEvent.type.in_(ALLERGY_NOTE_TYPES),
                TimelineEvent.status == "approved",
            )
            .order_by(TimelineEvent.occurred_at.desc())
        ).all()
        for note in notes:
            payload = note.payload or {}
            if not (payload.get("allergies") == [] or payload.get("assertion") == "no_known_allergies"):
                continue
            found.append(
                Finding(
                    "R5",
                    f"rule:R5:{note.id}",
                    "critical",
                    "Contradicting allergy documentation",
                    f"{note.title} records no known drug allergies, while the patient record "
                    f"contains: {', '.join(patient.allergies or [])}.",
                    "Reconcile the allergy history with the patient and correct the note.",
                    [note.id, *([allergy_event.id] if allergy_event else [])],
                )
            )

    # R6: a documented plan to hold or stop a drug is unresolved against the active order list.
    # Approved means not superseded: a replaced note no longer speaks for the record.
    metformin = ordered.get("metformin")
    round_notes = (
        db.scalars(
            select(TimelineEvent)
            .where(
                TimelineEvent.patient_id == patient.id,
                TimelineEvent.encounter_id == encounter.id,
                TimelineEvent.type == "round_note",
                TimelineEvent.status == "approved",
            )
            .order_by(TimelineEvent.occurred_at.desc())
        ).all()
        if ordered
        else []
    )
    if metformin:
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
            found.append(
                Finding(
                    "R6",
                    "rule:R6:metformin",
                    "warning",
                    "Unresolved plan action: hold metformin",
                    "The documented round plan says to hold metformin, but metformin remains on "
                    "the active inpatient order list with no documented resolution.",
                    "Resolve the plan action: stop or amend the order and document the decision.",
                    [note.id, metformin["event_id"]],
                )
            )
            break

    # R6 from the words of a note written in the app ("Stop metformin until ..."). A plan action for the
    # same drug on the same note decides instead, as in the claim-pack check.
    r6_found = {finding.key for finding in found if finding.rule_id == "R6"}
    for note in round_notes:
        payload = note.payload or {}
        plan_drugs = {
            str(action.get("drug", "")).lower()
            for action in (payload.get("plan_actions") or [])
            if isinstance(action, dict)
        }
        sentences = _sentences(note)
        for drug, med in ordered.items():
            key = f"rule:R6:{drug}"
            if not drug or key in r6_found or drug in plan_drugs:
                continue
            pattern = re.compile(rf"\b{HOLD_VERBS}\s+(?:the\s+)?{re.escape(drug)}\b", re.IGNORECASE)
            for sentence in sentences:
                match = pattern.search(sentence)
                if not match or NEGATION_BEFORE_RE.search(sentence[: match.start()]):
                    continue
                r6_found.add(key)
                found.append(
                    Finding(
                        "R6",
                        key,
                        "warning",
                        f"Unresolved plan action: hold {med['drug']}",
                        f'The round note says "{sentence}", but {med["drug"]} remains on the active '
                        "inpatient order list with no documented resolution.",
                        "Resolve the plan action: stop or amend the order and document the decision.",
                        [note.id, med["event_id"]],
                    )
                )
                break

    return found


def evaluate_rules(db: Session, patient: Patient, encounter: Encounter, state: dict[str, Any]) -> list[Alert]:
    """Deterministic safety rules. No LLM is called here by design.

    Returns the alerts created or reopened by this run. One problem has one alert: a second result for the
    same problem updates the open alert, and an open alert whose problem has gone is closed as resolved.
    """
    changed: list[Alert] = []
    produced: set[str] = set()
    seen_keys: set[str] = set()
    for finding in _findings(db, patient, encounter, state):
        if finding.key in seen_keys:
            continue
        seen_keys.add(finding.key)
        alert = _apply(db, patient, encounter, finding, produced)
        if alert:
            changed.append(alert)
    db.flush()

    stale = db.scalars(
        select(Alert).where(
            Alert.patient_id == patient.id,
            Alert.encounter_id == encounter.id,
            Alert.status == "open",
            Alert.dedupe_key.like(f"{KEY_PREFIX}%"),
        )
    ).all()
    for alert in stale:
        if alert.dedupe_key in produced:
            continue
        alert.status = "resolved"
        alert.resolution = f"No longer true: {alert.title}. The rules re-checked the record and found no matching problem."
        alert.resolved_at = utcnow()
        add_audit(
            db,
            "alert_auto_resolved",
            "alert",
            alert.id,
            patient.id,
            actor_type="system",
            actor_name="Rules engine",
            before={"status": "open"},
            after={"status": "resolved", "resolution": alert.resolution},
        )
    db.flush()
    return changed
