from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException
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
    DismissRequest,
    _state,
)

router = APIRouter()


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
                "created_at": alert.created_at.isoformat(),
                "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
            }
            for alert in rows
        ],
        "open_count": sum(1 for alert in rows if alert.status == "open"),
    }


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
def dismiss_alert(alert_id: str, body: DismissRequest, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status = "dismissed"
    alert.dismissed_by = acting_name()
    alert.dismissal_reason = body.reason.strip()
    alert.resolved_at = utcnow()
    add_audit(
        db,
        "alert_dismissed",
        "alert",
        alert.id,
        alert.patient_id,
        actor_name=alert.dismissed_by,
        after={"rule_id": alert.rule_id, "reason": alert.dismissal_reason},
    )
    db.commit()
    return {"id": alert.id, "status": alert.status, "reason": alert.dismissal_reason}
