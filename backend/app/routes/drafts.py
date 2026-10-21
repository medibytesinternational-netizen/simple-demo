from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..services.identity import require, require_feature_role
from ..services.identity import acting_name
from ..db import get_db, utcnow
from ..models import (
    Draft,
)
from ..services.drafts import (
    accept_tasks,
    approve_draft,
    draft_to_dict,
    reject_draft,
    update_draft,
)
from ..services.rules import evaluate_rules
from ..services.timeline import (
    add_audit,
    event_to_dict,
)
from .common import (
    AcceptTasksRequest,
    ApproveRequest,
    DraftPatchRequest,
    RejectRequest,
    VerifyAllergyRequest,
    _state,
    _task_dict,
)

router = APIRouter()


# --------------------------------------------------------------------------
# Drafts and approvals
# --------------------------------------------------------------------------
@router.get("/drafts")
def drafts(
    feature: str | None = None,
    encounter_id: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(Draft).order_by(Draft.created_at.desc()).limit(limit)
    if feature:
        stmt = stmt.where(Draft.feature == feature)
    if encounter_id:
        stmt = stmt.where(Draft.encounter_id == encounter_id)
    rows = list(db.scalars(stmt))
    return {"drafts": [draft_to_dict(draft) for draft in rows]}


@router.get("/drafts/{draft_id}")
def draft_detail(draft_id: str, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    return draft_to_dict(draft)


@router.patch("/drafts/{draft_id}", dependencies=[Depends(require("edit_draft"))])
def draft_patch(draft_id: str, body: DraftPatchRequest, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    require_feature_role("edit_draft", draft.feature)
    update_draft(db, draft, body.content, body.editor)
    db.commit()
    return draft_to_dict(draft)


@router.post("/drafts/{draft_id}/verify-allergy", dependencies=[Depends(require("verify_allergy"))])
def draft_verify_allergy(draft_id: str, body: VerifyAllergyRequest, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    if draft.feature != "F2":
        raise HTTPException(400, "Allergy verification applies to the F2 admission assessment")
    if draft.status in {"approved", "rejected"}:
        raise HTTPException(400, "This draft is no longer open for verification")
    content = dict(draft.content or {})
    allergies = [dict(item) for item in content.get("allergies_to_verify", [])]
    match = next(
        (item for item in allergies if str(item.get("substance", "")).lower() == body.substance.lower()),
        None,
    )
    if not match:
        raise HTTPException(404, "Allergy not found in this draft")
    actor = acting_name()
    match["verified"] = True
    match["verified_by"] = actor
    match["verified_at"] = utcnow().isoformat()
    if body.source_event_id:
        match["source_event_id"] = body.source_event_id
    content["allergies_to_verify"] = allergies
    draft.content = content
    draft.status = "human_edited"
    draft.edited_by = actor
    draft.updated_at = utcnow()
    flag_modified(draft, "content")
    add_audit(
        db,
        "allergy_verified",
        "draft",
        draft.id,
        draft.patient_id,
        actor_name=actor,
        after={
            "substance": body.substance,
            "source_event_id": match.get("source_event_id"),
        },
    )
    db.commit()
    return draft_to_dict(draft)


@router.post("/drafts/{draft_id}/approve", dependencies=[Depends(require("approve_draft"))])
def draft_approve(draft_id: str, body: ApproveRequest, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    require_feature_role("approve_draft", draft.feature)
    event = approve_draft(db, draft, body.content, body.approved_by)
    patient, encounter, state = _state(db, draft.encounter_id)
    created_alerts = evaluate_rules(db, patient, encounter, state)
    db.commit()
    return {
        "draft": draft_to_dict(draft),
        "event": event_to_dict(event) if event else None,
        "new_alerts": [{"id": alert.id, "rule_id": alert.rule_id, "title": alert.title} for alert in created_alerts],
    }


@router.post("/drafts/{draft_id}/reject", dependencies=[Depends(require("reject_draft"))])
def draft_reject(draft_id: str, body: RejectRequest, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    require_feature_role("reject_draft", draft.feature)
    reject_draft(db, draft, body.reason, body.actor)
    db.commit()
    return draft_to_dict(draft)


@router.post("/drafts/{draft_id}/accept-tasks", dependencies=[Depends(require("accept_tasks"))])
def draft_accept_tasks(draft_id: str, body: AcceptTasksRequest, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    tasks = accept_tasks(db, draft, body.indices, body.actor)
    db.commit()
    return {"tasks": [_task_dict(task) for task in tasks]}
