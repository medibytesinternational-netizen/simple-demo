from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..models import (
    InvestigationRequest,
)
from ..services.context import build_context
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.llm import generate_draft
from ..services.timeline import (
    add_audit,
)
from .common import (
    _investigation_dict,
    _state,
)

router = APIRouter()


# --------------------------------------------------------------------------
# Investigation and radiology requests (F10), smart referrals (F11)
# --------------------------------------------------------------------------
@router.get("/investigation-requests")
def investigation_requests(encounter_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(InvestigationRequest).order_by(InvestigationRequest.created_at.desc())
    if encounter_id:
        stmt = stmt.where(InvestigationRequest.encounter_id == encounter_id)
    else:
        _, current, _ = _state(db)
        stmt = stmt.where(InvestigationRequest.encounter_id == current.id)
    rows = list(db.scalars(stmt))
    return {"requests": [_investigation_dict(request) for request in rows]}


@router.post("/investigation-requests/generate")
def generate_investigation_request(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db, encounter_id)
    context = build_context(db, patient, encounter, state, "F10")
    content, llm_call = generate_draft(db, "F10", context)
    draft = create_draft(db, feature="F10", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode, "latency_ms": llm_call.latency_ms}}


@router.post("/investigation-requests/{request_id}/export")
def export_investigation_request(request_id: str, db: Session = Depends(get_db)):
    request = db.get(InvestigationRequest, request_id)
    if not request:
        raise HTTPException(404, "Investigation request not found")
    request.status = "exported"
    request.exported_at = utcnow()
    add_audit(
        db,
        "investigation_request_exported",
        "investigation_request",
        request.id,
        request.patient_id,
        after={"status": request.status, "study": request.study},
        meta={"note": "Demo export only; no laboratory or radiology transmission exists"},
    )
    db.commit()
    return _investigation_dict(request)
