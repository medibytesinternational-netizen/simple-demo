"""Write what a hospital system sent into the shared record.

Used by POST /api/ingest/fhir and by ``python -m app.integrations.pull``, so both go through the
same mappers and the same rules. The caller commits.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Encounter, Patient, TimelineEvent
from ..models_ext.s17_integration import IntegrationSync
from ..services.rules import evaluate_rules
from ..services.timeline import add_audit, add_event, get_state, new_id
from .fhir import bundle_to_events, source_label


def _version_number(value: Any) -> int | None:
    text = str(value) if value is not None else ""
    return int(text) if text.isdigit() else None


def _encounter_for(db: Session, patient: Patient) -> Encounter | None:
    rows = list(db.scalars(select(Encounter).where(Encounter.patient_id == patient.id)))
    active = [row for row in rows if row.status == "active"]
    pool = active or rows
    return max(pool, key=lambda row: row.admitted_at or utcnow()) if pool else None


def _base_name(entry: str) -> str:
    return entry.split(" — ")[0].strip().lower()


def _add_unique(current: list[str] | None, entry: str, key=lambda text: text.strip().lower()) -> list[str] | None:
    """A new list with ``entry`` appended, or None when it is already there."""
    items = list(current or [])
    if any(key(str(existing)) == key(entry) for existing in items):
        return None
    return [*items, entry]


def ingest_bundle(
    db: Session,
    system: str,
    bundle: dict[str, Any],
    mrn: str | None = None,
    kind: str = "inbound",
    extra_errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Create timeline events for a FHIR Bundle. Returns counts plus per-resource details."""
    started = utcnow()
    actor = f"{system} (FHIR)"
    source = source_label(system)
    mapped = bundle_to_events(bundle, system, mrn)
    details: list[dict[str, Any]] = []
    created = 0
    skipped = [dict(entry, outcome="skipped") for entry in mapped["skipped"]]
    errors = [dict(entry, outcome="error") for entry in [*mapped["errors"], *(extra_errors or [])]]
    touched: dict[str, Patient] = {}
    patients: dict[str, Patient | None] = {}
    known: dict[str, dict[str, list[TimelineEvent]]] = {}  # patient id -> external id -> events

    def events_for(patient: Patient) -> dict[str, list[TimelineEvent]]:
        if patient.id not in known:
            found: dict[str, list[TimelineEvent]] = {}
            rows = db.scalars(
                select(TimelineEvent).where(TimelineEvent.patient_id == patient.id, TimelineEvent.source == source)
            )
            for event in rows:
                external = (event.payload or {}).get("external_id")
                if external:
                    found.setdefault(external, []).append(event)
            known[patient.id] = found
        return known[patient.id]

    for item in mapped["items"]:
        if item["mrn"] not in patients:
            patients[item["mrn"]] = db.scalar(select(Patient).where(Patient.mrn == item["mrn"]))
        patient = patients[item["mrn"]]
        if patient is None:
            errors.append({"resource": item["resource"], "outcome": "error",
                           "reason": f"no patient with medical record number {item['mrn']}"})
            continue
        encounter = _encounter_for(db, patient)
        effects = item.get("effects", {})
        event = None
        if item["type"]:
            if encounter is None:
                errors.append({"resource": item["resource"], "outcome": "error", "reason": "patient has no encounter"})
                continue
            existing = events_for(patient).get(item["external_id"], [])
            supersedes = None
            if existing:
                best = max(existing, key=lambda e: _version_number((e.payload or {}).get("external_version")) or -1)
                old_version = _version_number((best.payload or {}).get("external_version"))
                new_version = _version_number(item["version"])
                if new_version is None or old_version is None or new_version <= old_version:
                    skipped.append({"resource": item["resource"], "outcome": "skipped",
                                    "reason": "already received at this version or newer"})
                    continue
                supersedes = best
            occurred = item["occurred_at"] or utcnow()
            if supersedes is not None:
                occurred = max(occurred, supersedes.occurred_at + timedelta(seconds=1))
            event = add_event(
                db,
                patient_id=patient.id,
                encounter_id=encounter.id,
                type=item["type"],
                title=item["title"],
                body_text=item["body_text"],
                payload=item["payload"],
                source=source,
                author_type="system",
                author_name=actor,
                status="approved",
                occurred_at=occurred,
                approved_by=actor,
                supersedes_event_id=supersedes.id if supersedes else None,
            )
            if supersedes is not None and supersedes.status == "approved":
                supersedes.status = "superseded"
            events_for(patient).setdefault(item["external_id"], []).append(event)
            add_audit(db, "fhir_event_ingested", "timeline_event", event.id, patient.id,
                      actor_type="system", actor_name=actor,
                      after={"type": event.type, "title": event.title},
                      meta={"external_id": item["external_id"], "version": item["version"],
                            "supersedes": supersedes.id if supersedes else None})
        changed = event is not None
        if effects.get("allergy"):
            updated = _add_unique(patient.allergies, effects["allergy"], key=_base_name)
            if updated is not None:
                patient.allergies = updated
                changed = True
        if effects.get("problem"):
            updated = _add_unique(patient.problems, effects["problem"])
            if updated is None:
                skipped.append({"resource": item["resource"], "outcome": "skipped", "reason": "problem already listed"})
                continue
            patient.problems = updated
            add_audit(db, "fhir_problem_added", "patient", patient.id, patient.id, actor_type="system",
                      actor_name=actor, after={"problem": effects["problem"]},
                      meta={"external_id": item["external_id"]})
            changed = True
        if changed:
            created += 1
            touched[patient.id] = patient
            details.append({"resource": item["resource"], "outcome": "created",
                            "event_id": event.id if event else None})

    alerts: list[str] = []
    for patient in touched.values():
        encounter = _encounter_for(db, patient)
        if encounter is not None:
            state = get_state(db, patient, encounter)
            alerts += [alert.id for alert in evaluate_rules(db, patient, encounter, state)]

    details += skipped + errors
    status = "ok"
    if errors:
        status = "failed" if not created and not skipped else "partial"
    finished = utcnow()
    db.add(
        IntegrationSync(
            id=new_id("syn"),
            system=system,
            kind=kind,
            status=status,
            created=created,
            skipped=len(skipped),
            errors=len(errors),
            detail=details[:200],
            patient_id=next(iter(touched), None),
            started_at=started,
            finished_at=finished,
        )
    )
    add_audit(db, "fhir_ingest", "integration", system, next(iter(touched), None), actor_type="system",
              actor_name=actor, after={"created": created, "skipped": len(skipped), "errors": len(errors)},
              meta={"kind": kind})
    db.flush()
    return {
        "created": created,
        "skipped": len(skipped),
        "errors": len(errors),
        "details": details,
        "alerts_created": alerts,
        "patients": mapped["patients"],
    }
