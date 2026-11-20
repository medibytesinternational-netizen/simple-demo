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
    if request.status not in ("approved", "requested"):
        raise HTTPException(409, "Only approved or requested investigations can be sent")
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


# --------------------------------------------------------------------------
# Investigation & radiology request form, hospital format: one report per request,
# stored as a document on the timeline so it can be reopened and printed.
# --------------------------------------------------------------------------
from ..config import settings  # noqa: E402
from ..models import Encounter, Patient  # noqa: E402
from ..services import investigation_form  # noqa: E402
from ..services.identity import ROLE_LABELS, acting_name, acting_user  # noqa: E402
from ..services.note_document import GENERATED_KIND  # noqa: E402
from ..services.ocr import new_document  # noqa: E402
from ..services.timeline import add_event  # noqa: E402


@router.post("/investigation-requests/{request_id}/report", dependencies=[Depends(require("investigation_report"))])
def investigation_request_report(request_id: str, db: Session = Depends(get_db)):
    request = db.get(InvestigationRequest, request_id)
    if not request:
        raise HTTPException(404, "Investigation request not found")
    patient = db.get(Patient, request.patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")
    encounter = db.get(Encounter, request.encounter_id) if request.encounter_id else None
    user = acting_user()
    made_at = utcnow()
    form = investigation_form.build(
        db, request, patient, encounter,
        {"name": user.name, "designation": ROLE_LABELS.get(user.role, user.role)}, made_at,
    )
    html = investigation_form.render_html(form)
    event = add_event(
        db, patient_id=patient.id, encounter_id=request.encounter_id, type=investigation_form.REPORT_TYPE, subtype="F10",
        title=f"{investigation_form.TITLE}: {request.study}", body_text=f"Request form for {request.study}",
        payload={"request_id": request.id, "study": request.study},
        source="F10", author_type="human", author_name=acting_name(), status="approved",
        occurred_at=made_at, approved_by=acting_name(),
    )
    folder = settings.uploads_dir / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{event.id}.html"
    path.write_text(html, encoding="utf-8")
    document = new_document(
        db, patient_id=patient.id, encounter_id=request.encounter_id,
        filename=f"{investigation_form.TITLE} {request.study} {patient.mrn} {made_at:%Y-%m-%d %H%M}.html", path=str(path),
        mime="text/html", image_kind=GENERATED_KIND, doc_type=investigation_form.REPORT_TYPE,
    )
    document.ocr_status = "confirmed"
    document.confirmed_by = acting_name()
    document.confirmed_at = made_at
    event.document_id = document.id
    add_audit(db, "note_document_stored", "document", document.id, patient.id,
              after={"event_id": event.id, "doc_type": investigation_form.REPORT_TYPE, "request_id": request.id})
    db.commit()
    return {"event_id": event.id, "document_id": document.id}
