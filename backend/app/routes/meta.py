from __future__ import annotations


from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..services.identity import require
from ..services.identity import acting_name, acting_user, current_patient_id
from .platform import allowed_actions, user_dict
from .. import clock
from ..config import settings
from ..db import get_db
from ..modules import module_registry
from ..models import (
    TimelineEvent,
)
from ..schemas import FEATURE_MODELS
from ..services.timeline import (
    add_audit,
    add_event,
    event_to_dict,
    get_encounter,
    get_event,
    get_patient,
    get_state,
)
from .common import (
    ConsentRequest,
    _state,
)

router = APIRouter()


# --------------------------------------------------------------------------
# Meta and patient
# --------------------------------------------------------------------------
@router.get("/meta")
def meta(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    return {
        "product": "MediBytes ARD",
        "patient": state["patient"],
        "encounter": state["encounter"],
        "demo_now": clock.now().replace(microsecond=0).isoformat(),
        "server_now": clock.real_utcnow().replace(microsecond=0).isoformat(),
        "llm_mode": settings.effective_llm_mode,
        "model": settings.openai_model,
        "live_available": bool(settings.openai_api_key),
        "demo_user": acting_name(),
        "demo_role": acting_user().role,
        "user": user_dict(acting_user()),
        "allowed_actions": allowed_actions(),
        "features": list(FEATURE_MODELS.keys()),
        "disclaimer": "Synthetic demo data. Not for clinical use.",
    }


@router.get("/modules")
def modules():
    return module_registry()


@router.get("/patients/{patient_id}")
def patient_detail(patient_id: str, db: Session = Depends(get_db)):
    patient = get_patient(db, patient_id)
    encounter = get_encounter(db)
    return {
        "patient": {
            "id": patient.id,
            "mrn": patient.mrn,
            "name": patient.name,
            "age": patient.age,
            "sex": patient.sex,
            "allergies": patient.allergies,
            "problems": patient.problems,
        },
        "state": get_state(db, patient, encounter),
    }


@router.get("/patients/{patient_id}/state")
def patient_state(patient_id: str, db: Session = Depends(get_db)):
    patient = get_patient(db, patient_id)
    encounter = get_encounter(db)
    return get_state(db, patient, encounter)


@router.get("/patients/{patient_id}/consents")
def patient_consents(patient_id: str, encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient = get_patient(db, patient_id)
    stmt = select(TimelineEvent).where(
        TimelineEvent.patient_id == patient.id,
        TimelineEvent.type == "consent",
    )
    if encounter_id:
        stmt = stmt.where(TimelineEvent.encounter_id == encounter_id)
    rows = list(db.scalars(stmt.order_by(TimelineEvent.occurred_at.desc())))
    return {
        "consents": [
            {
                "id": event.id,
                "consent_type": (event.payload or {}).get("consent_type"),
                "granted": (event.payload or {}).get("granted"),
                "actor": event.author_name,
                "note": (event.payload or {}).get("note", ""),
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in rows
        ]
    }


@router.post("/patients/{patient_id}/consents", dependencies=[Depends(require("consent"))])
def record_consent(patient_id: str, body: ConsentRequest, encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient = get_patient(db, patient_id)
    encounter = get_encounter(db, encounter_id)
    actor = acting_name()
    event = add_event(
        db,
        patient_id=patient.id,
        encounter_id=encounter.id,
        type="consent",
        subtype=body.consent_type,
        title=f"Consent — {body.consent_type.replace('_', ' ')}",
        body_text=(
            f"{'Granted' if body.granted else 'Declined'} by patient for "
            f"{body.consent_type.replace('_', ' ')}. {body.note}".strip()
        ),
        payload={
            "consent_type": body.consent_type,
            "granted": body.granted,
            "note": body.note,
            "captured_by": actor,
        },
        source="consent",
        author_type="human",
        author_name=actor,
        status="approved",
        approved_by=actor,
    )
    add_audit(
        db,
        "consent_recorded",
        "timeline_event",
        event.id,
        patient.id,
        actor_name=actor,
        after={"consent_type": body.consent_type, "granted": body.granted},
    )
    db.commit()
    return {
        "id": event.id,
        "consent_type": body.consent_type,
        "granted": body.granted,
        "occurred_at": event.occurred_at.isoformat(),
    }


# --------------------------------------------------------------------------
# F16 Unified patient timeline: who recorded it, when, from which source
# --------------------------------------------------------------------------
SOURCE_LABELS = {
    "F1": "Consultation note draft",
    "F2": "Admission note draft",
    "F3": "Round note draft",
    "F4": "Progress note draft",
    "F6": "Medicine reconciliation draft",
    "F7": "ICU flow sheet draft",
    "F9": "Discharge summary draft",
    "F10": "Investigation request draft",
    "F11": "Referral draft",
    "F12": "Claim review draft",
    "F13": "Revenue review draft",
    "consent": "Consent record",
    "lab": "Lab report scan",
    "device": "Bedside device reading",
    "seed": "Demo seed data",
    "human": "Typed by a person",
}


def source_label(source: str | None) -> str:
    """A readable name for where an event came from; hospital feeds (fhir:<system>) are shown as is."""
    raw = (source or "").strip()
    if not raw:
        return "Unknown source"
    if raw.lower().startswith("fhir:"):
        return raw
    if raw in SOURCE_LABELS:
        return SOURCE_LABELS[raw]
    text = raw.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def enrich_event(event: TimelineEvent, superseded_by: str | None = None) -> dict:
    """The stored event plus who drafted it, who recorded or approved it, and where it came from."""
    out = event_to_dict(event)
    is_model = event.author_type == "model"
    author = event.author_name or "Unknown"
    approver = event.approved_by
    if is_model:
        out["drafted_by"] = author
        out["recorded_by"] = approver or author
        out["authorship"] = (
            f"Drafted by {author}, approved by {approver}" if approver else f"Drafted by {author}, not yet approved"
        )
    else:
        out["drafted_by"] = None
        out["recorded_by"] = author
        out["authorship"] = f"Recorded by {author}"
    out["approved_by"] = approver
    out["ai_drafted"] = is_model
    out["source_label"] = source_label(event.source)
    out["superseded_by"] = superseded_by
    return out


def _replacements(db: Session, ids: list[str]) -> dict[str, str]:
    """Map event id to the id of the event that replaced it (the latest replacer wins)."""
    if not ids:
        return {}
    rows = db.execute(
        select(TimelineEvent.id, TimelineEvent.supersedes_event_id)
        .where(TimelineEvent.supersedes_event_id.in_(ids))
        .order_by(TimelineEvent.created_at.asc(), TimelineEvent.id.asc())
    ).all()
    return {old: new for new, old in rows}


def supersedes_chain(db: Session, event: TimelineEvent) -> list[dict]:
    """Every earlier version this event replaced, nearest first."""
    chain: list[dict] = []
    seen = {event.id}
    current = event
    while current.supersedes_event_id and current.supersedes_event_id not in seen:
        previous = db.get(TimelineEvent, current.supersedes_event_id)
        if not previous:
            break
        seen.add(previous.id)
        item = enrich_event(previous, current.id)
        chain.append(
            {
                "id": previous.id,
                "title": previous.title,
                "status": previous.status,
                "occurred_at": item["occurred_at"],
                "recorded_by": item["recorded_by"],
                "source_label": item["source_label"],
            }
        )
        current = previous
    return chain


def _parse_when(value: str | None, name: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be a date or an ISO date and time, for example 2026-05-01 or 2026-05-01T08:30") from None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


VISIBLE_STATUSES = ["approved", "superseded"]


@router.get("/patients/{patient_id}/timeline")
def patient_timeline(
    patient_id: str,
    encounter_id: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    types: str | None = None,
    source: str | None = None,
    before: str | None = None,
    after: str | None = None,
    db: Session = Depends(get_db),
):
    patient = get_patient(db, patient_id)
    wanted_types = [item.strip() for item in (types or "").split(",") if item.strip()]
    before_at = _parse_when(before, "before")
    after_at = _parse_when(after, "after")

    scope = [TimelineEvent.patient_id == patient.id, TimelineEvent.status.in_(VISIBLE_STATUSES)]
    if encounter_id:
        scope.append(TimelineEvent.encounter_id == encounter_id)

    stmt = select(TimelineEvent).where(*scope)
    if wanted_types:
        stmt = stmt.where(TimelineEvent.type.in_(wanted_types))
    if source:
        stmt = stmt.where(func.lower(TimelineEvent.source) == source.strip().lower())
    if before_at:
        stmt = stmt.where(TimelineEvent.occurred_at < before_at)
    if after_at:
        stmt = stmt.where(TimelineEvent.occurred_at >= after_at)
    stmt = stmt.order_by(
        TimelineEvent.occurred_at.desc(), TimelineEvent.created_at.desc(), TimelineEvent.id.desc()
    ).limit(limit)
    events = list(db.scalars(stmt))
    replaced = _replacements(db, [event.id for event in events])

    # Filter choices come from the whole visible record, so they do not shrink while filtering.
    facet_rows = db.execute(select(TimelineEvent.type, TimelineEvent.source).where(*scope).distinct()).all()
    facet_sources = sorted({row[1] for row in facet_rows if row[1]})
    return {
        "events": [enrich_event(event, replaced.get(event.id)) for event in events],
        "count": len(events),
        "facets": {
            "types": sorted({row[0] for row in facet_rows if row[0]}),
            "sources": [{"source": item, "label": source_label(item)} for item in facet_sources],
        },
        "filters": {"types": wanted_types, "source": source, "before": before, "after": after},
    }


@router.get("/events/{event_id}")
def event_detail(event_id: str, db: Session = Depends(get_db)):
    event = get_event(db, event_id)
    if event.patient_id != current_patient_id():
        raise ValueError("Event belongs to another patient")
    out = enrich_event(event, _replacements(db, [event.id]).get(event.id))
    out["supersedes"] = supersedes_chain(db, event)
    return out
