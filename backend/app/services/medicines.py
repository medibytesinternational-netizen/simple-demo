"""F6 medicines: reconciliation decisions, medicine orders and administrations.

Three different facts are kept apart (PRD rule 4):
- a reconciliation decision says what a clinician thinks should happen (no order is created);
- a ``med_order`` event is an order placed by a doctor;
- a ``medication_administration`` event is a dose a nurse recorded as given, held or refused.

SPEC-007 and SPEC-013 read ``med_order`` and ``medication_administration`` events by name, so the
payload keys below must not change.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..models import Encounter, Patient, TimelineEvent
from ..models_ext.f06_decisions import ReconciliationDecision
from .identity import acting_name
from .reconciliation import reconciliation
from .timeline import add_audit, add_event, get_encounter, get_patient, get_state, new_id, require_open_encounter

DECISIONS = ("continue", "hold", "stop", "change")
ORDER_FIELDS = ("dose", "route", "frequency", "indication")


# --------------------------------------------------------------------------
# Reconciliation decisions
# --------------------------------------------------------------------------
def load_decisions(db: Session, patient: Patient, encounter: Encounter) -> list[dict[str, Any]]:
    """Decisions for this encounter, oldest first (the newest one wins when merged)."""
    rows = db.scalars(
        select(ReconciliationDecision)
        .where(
            ReconciliationDecision.patient_id == patient.id,
            ReconciliationDecision.encounter_id == encounter.id,
        )
        .order_by(ReconciliationDecision.decided_at, ReconciliationDecision.id)
    )
    return [
        {
            "id": row.id,
            "discrepancy_id": row.discrepancy_id,
            "decision": row.decision,
            "note": row.note,
            "decided_by": row.decided_by,
            "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            "fingerprint": row.fingerprint,
        }
        for row in rows
    ]


def reconciliation_with_decisions(
    db: Session, patient: Patient, encounter: Encounter, state: dict[str, Any]
) -> dict[str, Any]:
    return reconciliation(state, load_decisions(db, patient, encounter))


def unresolved_discrepancies(
    db: Session, patient: Patient, encounter: Encounter, state: dict[str, Any]
) -> list[dict[str, Any]]:
    """Discrepancies nobody has decided yet. The discharge readiness check uses this."""
    result = reconciliation_with_decisions(db, patient, encounter, state)
    return [item for item in result["discrepancies"] if item["status"] == "open"]


def proposed_order_change(item: dict[str, Any], decision: str, note: str) -> dict[str, Any] | None:
    """What a doctor could order after the decision. Nothing is ordered here."""
    if decision == "continue":
        return None
    action = decision
    if decision == "change" and not item.get("current_order"):
        action = "start"
    return {
        "decision": decision,
        "action": action,
        "drug": item.get("drug"),
        "current_order": item.get("current_order"),
        "reason": note,
        "evidence_event_ids": item.get("evidence_event_ids", []),
        "ordered": False,
        "message": "Nothing has been ordered. A doctor places any order from Medicine orders.",
    }


def record_decision(
    db: Session,
    patient: Patient,
    encounter: Encounter,
    state: dict[str, Any],
    discrepancy_id: str,
    decision: str,
    note: str,
) -> dict[str, Any]:
    """Store one decision and write it to the timeline. Creates no order."""
    require_open_encounter(encounter)
    current = reconciliation_with_decisions(db, patient, encounter, state)
    item = next((entry for entry in current["discrepancies"] if entry["id"] == discrepancy_id), None)
    if item is None:
        raise LookupError(discrepancy_id)
    actor = acting_name()
    now = clock.now()
    row = ReconciliationDecision(
        id=new_id("rdc"),
        patient_id=patient.id,
        encounter_id=encounter.id,
        discrepancy_id=discrepancy_id,
        decision=decision,
        note=note,
        decided_by=actor,
        decided_at=now,
        fingerprint=item["fingerprint"],
    )
    db.add(row)
    event = add_event(
        db,
        patient_id=patient.id,
        encounter_id=encounter.id,
        type="reconciliation_decision",
        subtype=decision,
        title=f"Reconciliation: {decision} {item['drug']}",
        body_text=note,
        payload={
            "discrepancy_id": discrepancy_id,
            "decision": decision,
            "note": note,
            "decided_by": actor,
            "drug": item["drug"],
            "kind": item["kind"],
            "evidence_event_ids": item["evidence_event_ids"],
        },
        source="F6",
        author_type="human",
        author_name=actor,
        occurred_at=now,
    )
    add_audit(
        db,
        "reconciliation_decision",
        "reconciliation_decision",
        row.id,
        patient.id,
        after={"discrepancy_id": discrepancy_id, "decision": decision, "event_id": event.id},
    )
    db.flush()
    return {"decision": row, "event": event, "discrepancy": item}


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------
def _active_order(state: dict[str, Any], drug: str) -> dict[str, Any] | None:
    return next((med for med in state["active_meds"] if str(med["drug"]).lower() == drug.lower()), None)


def _order_time(db: Session, patient: Patient, encounter: Encounter, drug: str) -> datetime:
    """Now on the demo clock, but never before an earlier order for the same drug."""
    now = clock.now()
    events = db.scalars(
        select(TimelineEvent).where(
            TimelineEvent.patient_id == patient.id,
            TimelineEvent.encounter_id == encounter.id,
            TimelineEvent.type == "med_order",
        )
    )
    latest = max(
        (e.occurred_at for e in events if str((e.payload or {}).get("drug", "")).lower() == drug.lower()),
        default=None,
    )
    if latest is not None and latest >= now:
        return latest + timedelta(seconds=1)
    return now


def place_order(
    db: Session,
    patient: Patient,
    encounter: Encounter,
    *,
    action: str,
    drug: str,
    reason: str,
    fields: dict[str, str | None],
) -> TimelineEvent:
    """Start, stop or change an inpatient medicine. The caller must be allowed to order."""
    require_open_encounter(encounter)
    state = get_state(db, patient, encounter)
    active = _active_order(state, drug)
    given = {key: (fields.get(key) or "").strip() for key in ORDER_FIELDS}
    if action == "start":
        if active:
            raise ValueError(f"{active['drug']} is already active. Use change to alter the order.")
        values = given
        name = drug
    elif action == "stop":
        if not active:
            raise ValueError(f"There is no active order for {drug} to stop.")
        values = {key: str(active.get(key, "") or "") for key in ORDER_FIELDS}
        name = active["drug"]
    else:  # change
        if not active:
            raise ValueError(f"There is no active order for {drug} to change. Use start.")
        if not any(given.values()):
            raise ValueError("Give at least one of dose, route, frequency or indication to change.")
        values = {key: given[key] or str(active.get(key, "") or "") for key in ORDER_FIELDS}
        if all(_norm(values[key]) == _norm(str(active.get(key, "") or "")) for key in ORDER_FIELDS):
            raise ValueError("The change is the same as the active order.")
        name = active["drug"]

    actor = acting_name()
    verb = {"start": "Started", "stop": "Stopped", "change": "Changed"}[action]
    label = " ".join(part for part in (name, values["dose"], values["route"], values["frequency"]) if part)
    event = add_event(
        db,
        patient_id=patient.id,
        encounter_id=encounter.id,
        type="med_order",
        subtype="inpatient",
        title=f"{verb} — {label}",
        body_text=reason,
        payload={
            "drug": name,
            "dose": values["dose"],
            "route": values["route"],
            "frequency": values["frequency"],
            "indication": values["indication"],
            "kind": "inpatient",
            "status": "stopped" if action == "stop" else "active",
            "reason": reason,
            "action": action,
            "ordered_by": actor,
        },
        source="F6",
        author_type="human",
        author_name=actor,
        occurred_at=_order_time(db, patient, encounter, name),
    )
    add_audit(
        db,
        f"medicine_{action}",
        "timeline_event",
        event.id,
        patient.id,
        after={"drug": name, "action": action, "reason": reason},
    )
    return event


def _norm(value: str) -> str:
    return "".join(value.lower().split())


# --------------------------------------------------------------------------
# Administrations
# --------------------------------------------------------------------------
def _parse_time(value: str | None) -> datetime:
    if not value:
        return clock.now()
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("given_at must be an ISO date and time, for example 2026-10-20T09:30:00") from exc
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def record_administration(
    db: Session,
    order_event_id: str,
    *,
    status: str,
    given_at: str | None,
    note: str | None,
) -> TimelineEvent:
    """Record that a dose was given, held or refused. Needs the CURRENT active order."""
    order = db.get(TimelineEvent, order_event_id)
    patient = get_patient(db)
    if not order or order.patient_id != patient.id:
        raise LookupError(order_event_id)
    if order.type != "med_order":
        raise ValueError("That event is not a medicine order, so no dose can be recorded against it.")
    encounter = get_encounter(db, order.encounter_id)
    require_open_encounter(encounter)
    state = get_state(db, patient, encounter)
    active = next((med for med in state["active_meds"] if med["event_id"] == order.id), None)
    if active is None:
        raise ValueError("That is not the current active order for this medicine, so no dose can be recorded against it.")
    when = _parse_time(given_at)
    actor = acting_name()
    event = add_event(
        db,
        patient_id=patient.id,
        encounter_id=encounter.id,
        type="medication_administration",
        subtype=status,
        title=f"{status.capitalize()} — {active['drug']} {active.get('dose', '')}".strip(),
        body_text=(note or "").strip(),
        payload={
            "drug": active["drug"],
            "dose": active.get("dose", ""),
            "route": active.get("route", ""),
            "status": status,
            "given_at": when.isoformat(),
            "order_event_id": order.id,
            "note": (note or "").strip(),
            "recorded_by": actor,
        },
        source="F6",
        author_type="human",
        author_name=actor,
        occurred_at=when,
    )
    add_audit(
        db,
        "medication_administration",
        "timeline_event",
        event.id,
        patient.id,
        after={"drug": active["drug"], "status": status, "order_event_id": order.id},
    )
    return event


def list_administrations(db: Session, patient: Patient, encounter_id: str | None = None) -> list[dict[str, Any]]:
    stmt = select(TimelineEvent).where(
        TimelineEvent.patient_id == patient.id,
        TimelineEvent.type == "medication_administration",
        TimelineEvent.status == "approved",
    )
    if encounter_id:
        stmt = stmt.where(TimelineEvent.encounter_id == encounter_id)
    stmt = stmt.order_by(TimelineEvent.occurred_at.desc(), TimelineEvent.created_at.desc())
    return [{"event_id": event.id, "encounter_id": event.encounter_id, **(event.payload or {})} for event in db.scalars(stmt)]
