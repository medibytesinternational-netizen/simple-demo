from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..services.identity import require
from ..services.identity import acting_name
from ..db import get_db, utcnow
from ..models import (
    Alert,
)
from ..services.rules import evaluate_rules
from ..services.timeline import (
    add_audit,
)
from .common import (
    _state,
)

router = APIRouter()

RULE_IDS = ("R1", "R2", "R3", "R4", "R5", "R6")
QUALITY_NOTE = "Small sample: based on clinician dismissals."


class AlertDismissRequest(BaseModel):
    """A dismissal says why, and in which of three ways the alert was (not) useful."""

    category: Literal["false_positive", "known_and_accepted", "acted_on"]
    reason: str = Field(min_length=10)


# --------------------------------------------------------------------------
# Safety
# --------------------------------------------------------------------------
@router.get("/alerts")
def alerts(encounter_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Alert).order_by(Alert.created_at.desc())
    if encounter_id:
        stmt = stmt.where(Alert.encounter_id == encounter_id)
    else:
        _, current, _ = _state(db)
        stmt = stmt.where(Alert.encounter_id == current.id)
    rows = list(db.scalars(stmt))
    return {
        "alerts": [
            {
                "id": alert.id,
                "rule_id": alert.rule_id,
                "severity": alert.severity,
                "status": alert.status,
                "title": alert.title,
                "explanation": alert.explanation,
                "recommended_action": alert.recommended_action,
                "evidence_event_ids": alert.evidence_event_ids or [],
                "acknowledged_by": alert.acknowledged_by,
                "dismissed_by": alert.dismissed_by,
                "dismissal_reason": alert.dismissal_reason,
                "dismissal_category": alert.dismissal_category,
                "resolution": alert.resolution,
                "created_at": alert.created_at.isoformat(),
                "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
            }
            for alert in rows
        ],
        "open_count": sum(1 for alert in rows if alert.status == "open"),
    }


@router.get("/alerts/quality")
def alert_quality(db: Session = Depends(get_db)):
    """How often each rule's alerts are useful, from clinician dismissals. Hospital-wide, all patients."""
    rows = list(db.scalars(select(Alert)))
    rules = []
    sample = 0
    for rule_id in RULE_IDS:
        mine = [alert for alert in rows if alert.rule_id == rule_id]
        false_positive = sum(1 for a in mine if a.dismissal_category == "false_positive")
        known = sum(1 for a in mine if a.dismissal_category == "known_and_accepted")
        acted = sum(1 for a in mine if a.dismissal_category == "acted_on")
        useful = known + acted
        categorised = useful + false_positive
        sample += categorised
        rules.append(
            {
                "rule_id": rule_id,
                "opened": len(mine),
                "open": sum(1 for a in mine if a.status == "open"),
                "false_positive": false_positive,
                "known_and_accepted": known,
                "acted_on": acted,
                "auto_resolved": sum(1 for a in mine if a.status == "resolved"),
                "precision": useful / categorised if categorised else None,
            }
        )
    return {"rules": rules, "sample_size": sample, "note": QUALITY_NOTE}


@router.post("/alerts/evaluate", dependencies=[Depends(require("run_rules"))])
def evaluate_alerts(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    created = evaluate_rules(db, patient, encounter, state)
    db.commit()
    return {"created": [{"id": alert.id, "rule_id": alert.rule_id, "title": alert.title} for alert in created]}


@router.post("/alerts/{alert_id}/acknowledge", dependencies=[Depends(require("acknowledge_alert"))])
def acknowledge_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status = "acknowledged"
    alert.acknowledged_by = acting_name()
    alert.resolved_at = utcnow()
    add_audit(
        db,
        "alert_acknowledged",
        "alert",
        alert.id,
        alert.patient_id,
        after={"rule_id": alert.rule_id, "status": alert.status},
    )
    db.commit()
    return {"id": alert.id, "status": alert.status}


@router.post("/alerts/{alert_id}/dismiss", dependencies=[Depends(require("dismiss_alert"))])
def dismiss_alert(alert_id: str, body: AlertDismissRequest, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status = "dismissed"
    alert.dismissed_by = acting_name()
    alert.dismissal_reason = body.reason.strip()
    alert.dismissal_category = body.category
    alert.resolved_at = utcnow()
    add_audit(
        db,
        "alert_dismissed",
        "alert",
        alert.id,
        alert.patient_id,
        actor_name=alert.dismissed_by,
        after={"rule_id": alert.rule_id, "reason": alert.dismissal_reason, "category": alert.dismissal_category},
    )
    db.commit()
    return {
        "id": alert.id,
        "status": alert.status,
        "reason": alert.dismissal_reason,
        "category": alert.dismissal_category,
    }
