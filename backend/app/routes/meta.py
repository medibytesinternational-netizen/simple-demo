from __future__ import annotations


from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..services.identity import require
from ..services.identity import acting_name, acting_user
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
    list_events,
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


@router.get("/patients/{patient_id}/timeline")
def patient_timeline(
    patient_id: str,
    encounter_id: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    get_patient(db, patient_id)
    events = list_events(db, patient_id, encounter_id, approved_only=True, limit=limit)
    return {"events": [event_to_dict(event) for event in events], "count": len(events)}


@router.get("/events/{event_id}")
def event_detail(event_id: str, db: Session = Depends(get_db)):
    return event_to_dict(get_event(db, event_id))
