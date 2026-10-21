from __future__ import annotations


from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..models import (
    InvestigationRequest,
)
from ..services.identity import require
from ..services.context import build_context
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.cached.f10_investigation import resolve_study
from ..services.llm import generate_draft
from ..services.timeline import (
    add_audit,
)
from .common import (
    _investigation_dict,
    _state,
)

router = APIRouter()


class InvestigationGenerateRequest(BaseModel):
    study: str | None = None
    request_type: Literal["laboratory", "imaging"] | None = None


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


@router.post("/investigation-requests/generate", dependencies=[Depends(require("clinical_draft"))])
def generate_investigation_request(
    body: InvestigationGenerateRequest | None = None,
    encounter_id: str | None = None,
    db: Session = Depends(get_db),
):
    body = body or InvestigationGenerateRequest()
    patient, encounter, state = _state(db, encounter_id)
    context = build_context(db, patient, encounter, state, "F10")
    try:
        study, request_type = resolve_study(context, body.study, body.request_type)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    context["requested_study"] = study
    context["requested_type"] = request_type
    content, llm_call = generate_draft(db, "F10", context)
    # The clinician's choice (or the inference from the record) stands even if a live model drifts.
    content["study"] = study
    content["request_type"] = request_type
    draft = create_draft(db, feature="F10", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode, "latency_ms": llm_call.latency_ms}}


@router.post("/investigation-requests/{request_id}/export", dependencies=[Depends(require("send_request"))])
def export_investigation_request(request_id: str, db: Session = Depends(get_db)):
    request = db.get(InvestigationRequest, request_id)
    if not request:
        raise HTTPException(404, "Investigation request not found")
    if request.status == "exported":
        raise HTTPException(409, "This request has already been exported")
    if request.status != "approved":
        raise HTTPException(409, "Only approved requests can be exported")
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
