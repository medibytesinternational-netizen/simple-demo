"""F9 discharge rules: what must exist, what needs a reason, what happens to open work.

PRD journey stage 4: "Open tasks escalated." A discharge is blocked when required documentation is
missing (no override can bypass that). Open critical alerts and open tasks are allowed only with a
written reason, which is audited. Tasks still open at discharge are escalated.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import utcnow
from ...models import Alert, Encounter, Patient, Task
from ..identity import acting_name
from ..medicines import unresolved_discrepancies
from ..timeline import EncounterLocked, add_audit, get_state, list_events
from . import ApprovalContext, after_commit, validator

MIN_REASON = 10
CLOSED_TASK_STATES = {"completed", "cancelled"}
OPEN_AT_DISCHARGE = "Open at discharge"

# (event type, label, where it comes from)
REQUIRED = [
    ("consult_note", "Consultation note", "F1"),
    ("admission_note", "Admission assessment", "F2"),
    ("round_note", "Round handover", "F3"),
    ("lab_result", "Laboratory results", "Labs"),
    ("procedure", "Procedures documented", "Care"),
]


class DischargeBlocked(EncounterLocked):
    """Raised when a discharge may not go ahead; mapped to HTTP 409 by the shared handler."""


def open_critical_alerts(db: Session, patient: Patient, encounter: Encounter) -> list[Alert]:
    return list(
        db.scalars(
            select(Alert)
            .where(
                Alert.patient_id == patient.id,
                Alert.encounter_id == encounter.id,
                Alert.status == "open",
                Alert.severity == "critical",
            )
            .order_by(Alert.created_at, Alert.id)
        )
    )


def open_tasks(db: Session, patient: Patient, encounter: Encounter) -> list[Task]:
    return list(
        db.scalars(
            select(Task)
            .where(
                Task.patient_id == patient.id,
                Task.encounter_id == encounter.id,
                Task.status.notin_(list(CLOSED_TASK_STATES)),
            )
            .order_by(Task.created_at, Task.id)
        )
    )


def _difference_title(item: dict[str, Any]) -> str:
    return f"{item['drug']} - {str(item['kind']).replace('_', ' ')}"


def discharge_readiness(db: Session, patient: Patient, encounter: Encounter) -> dict[str, Any]:
    """One answer for the readiness endpoint and the approval validator.

    ``ready`` means the required documentation exists. Warnings do not clear it: they need a
    written reason when the summary is approved.
    """
    events = list_events(db, patient.id, encounter.id, approved_only=True, limit=1000)
    types = {event.type for event in events}
    items = [
        {"key": key, "label": label, "present": key in types, "source": source}
        for key, label, source in REQUIRED
    ]
    alerts = open_critical_alerts(db, patient, encounter)
    tasks = open_tasks(db, patient, encounter)
    differences = unresolved_discrepancies(db, patient, encounter, get_state(db, patient, encounter))
    warnings = {
        "open_critical_alerts": [{"id": alert.id, "title": alert.title} for alert in alerts],
        "open_tasks": [{"id": task.id, "title": task.title} for task in tasks],
        "unresolved_medicine_differences": [
            {"id": item["id"], "title": _difference_title(item)} for item in differences
        ],
    }
    return {
        "items": items,
        "warnings": warnings,
        "ready": all(item["present"] for item in items),
        "needs_override": any(warnings.values()),
    }


@validator("F9")
def check_discharge(ctx: ApprovalContext) -> None:
    readiness = discharge_readiness(ctx.db, ctx.patient, ctx.encounter)
    missing = [item["label"] for item in readiness["items"] if not item["present"]]
    if missing:
        raise DischargeBlocked(
            "Discharge is blocked: required documentation is missing (" + ", ".join(missing) + "). "
            "Document it first; a reason cannot replace it."
        )
    alerts = readiness["warnings"]["open_critical_alerts"]
    tasks = readiness["warnings"]["open_tasks"]
    differences = readiness["warnings"]["unresolved_medicine_differences"]
    if not alerts and not tasks and not differences:
        return
    reason = str((ctx.override or {}).get("reason") or "").strip()
    if len(reason) < MIN_REASON:
        parts = []
        if alerts:
            parts.append("open critical alerts: " + "; ".join(item["title"] for item in alerts))
        if tasks:
            parts.append("open tasks: " + "; ".join(item["title"] for item in tasks))
        if differences:
            parts.append("unresolved medicine differences: " + "; ".join(item["title"] for item in differences))
        raise DischargeBlocked(
            f"Discharge needs a reason of at least {MIN_REASON} characters because of " + " | ".join(parts) + "."
        )
    add_audit(
        ctx.db,
        "discharge_override",
        "encounter",
        ctx.encounter.id,
        ctx.patient.id,
        actor_name=ctx.approver,
        after={"reason": reason, "open_critical_alerts": alerts, "open_tasks": tasks, "unresolved_medicine_differences": differences},
        meta={"draft_id": ctx.draft.id},
    )


@after_commit("F9")
def escalate_open_tasks(ctx: ApprovalContext, event: Any) -> None:
    """Work still open at discharge goes up to at least level 1, with the reason, audited each."""
    now = utcnow()
    for task in open_tasks(ctx.db, ctx.patient, ctx.encounter):
        before = {
            "escalation_level": task.escalation_level or 0,
            "escalation_reason": task.escalation_reason,
        }
        task.escalation_level = max(task.escalation_level or 0, 1)
        task.escalated_at = now
        task.escalation_reason = OPEN_AT_DISCHARGE
        add_audit(
            ctx.db,
            "task_escalated",
            "task",
            task.id,
            task.patient_id,
            actor_name=acting_name(),
            before=before,
            after={
                "escalation_level": task.escalation_level,
                "escalation_reason": task.escalation_reason,
                "kind": "discharge",
            },
            meta={"draft_id": ctx.draft.id, "title": task.title},
        )


@after_commit("F9")
def close_encounter(ctx: ApprovalContext, event: Any) -> None:
    ctx.encounter.status = "discharged"
    ctx.encounter.discharged_at = utcnow()
