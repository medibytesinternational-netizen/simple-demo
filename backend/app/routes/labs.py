from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..services.identity import require
from ..services.identity import acting_name
from ..db import get_db, utcnow
from ..models import (
    Alert,
)
from ..services.timeline import (
    add_audit,
    event_to_dict,
    get_event,
)
from .common import (
    _state,
)

router = APIRouter()


@router.get("/investigations")
def investigations(encounter_id: str | None = None, db: Session = Depends(get_db)):
    _, _, state = _state(db, encounter_id)
    return {
        "labs": state["latest_labs"],
        "unreviewed": state["unreviewed_labs"],
        "reviewed_count": len(state["latest_labs"]) - len(state["unreviewed_labs"]),
    }


@router.post("/labs/{event_id}/review", dependencies=[Depends(require("review_lab"))])
def review_lab(event_id: str, db: Session = Depends(get_db)):
    event = get_event(db, event_id)
    if event.type != "lab_result":
        raise HTTPException(400, "Event is not a laboratory result")
    before = dict(event.payload or {})
    event.payload = {**before, "review_status": "reviewed"}
    flag_modified(event, "payload")
    add_audit(
        db,
        "lab_reviewed",
        "timeline_event",
        event.id,
        event.patient_id,
        before=before,
        after=event.payload,
    )
    alerts = list(
        db.scalars(
            select(Alert).where(
                Alert.status == "open",
                Alert.rule_id == "R3",
                Alert.patient_id == event.patient_id,
            )
        )
    )
    for alert in alerts:
        if event.id in (alert.evidence_event_ids or []):
            alert.status = "acknowledged"
            alert.acknowledged_by = acting_name()
            alert.resolved_at = utcnow()
            add_audit(
                db,
                "alert_acknowledged",
                "alert",
                alert.id,
                event.patient_id,
                after={"reason": "Result reviewed", "lab_event_id": event.id},
            )
    db.commit()
    return {"event": event_to_dict(event)}
