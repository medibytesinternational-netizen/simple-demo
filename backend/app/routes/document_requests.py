from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..services.identity import require
from ..services.identity import acting_name
from ..db import get_db, utcnow
from ..models import (
    Document,
    DocumentRequest,
)
from ..services.revenue import claim_prep
from ..services.timeline import (
    add_audit,
    new_id,
)
from .common import (
    DocumentRequestGenerateRequest,
    MatchRequest,
    _request_dict,
    _state,
)

router = APIRouter()


# --------------------------------------------------------------------------
# Document requests (supporting follow-up, not F10)
# --------------------------------------------------------------------------
@router.get("/document-requests")
def document_requests(encounter_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(DocumentRequest).order_by(DocumentRequest.created_at.desc())
    if encounter_id:
        stmt = stmt.where(DocumentRequest.encounter_id == encounter_id)
    rows = list(db.scalars(stmt))
    return {"requests": [_request_dict(request) for request in rows]}


@router.post("/document-requests/generate", dependencies=[Depends(require("records_request"))])
def generate_document_request(body: DocumentRequestGenerateRequest | None = None, db: Session = Depends(get_db)):
    """Supporting follow-up request for missing records or pre-authorization.

    This is deliberately separate from F10, which is the investigation/radiology
    requisition workflow. No external transmission is performed.
    """
    patient, encounter, state = _state(db)
    prep = claim_prep(db, patient, encounter, state)
    records = [item["label"] for item in prep["missing_documents"]] or ["Signed discharge summary"]
    request = DocumentRequest(
        id=new_id("req"),
        patient_id=patient.id,
        encounter_id=encounter.id,
        request_type=(body.request_type if body and body.request_type else "pre_auth"),
        records_requested=records,
        recipient="Star Health — Provider Desk",
        justification="Required before the claim pack can enter clinical review. Demo only; no transmission.",
        due_at=utcnow() + timedelta(days=3),
        status="approved",
        created_at=utcnow(),
        approved_by=acting_name(),
    )
    db.add(request)
    add_audit(
        db,
        "document_request_created",
        "document_request",
        request.id,
        patient.id,
        after={"records": records, "recipient": request.recipient},
        meta={"note": "Supporting follow-up only; no external transmission"},
    )
    db.commit()
    return {"request": _request_dict(request), "missing_documents": prep["missing_documents"]}


@router.post("/document-requests/{request_id}/export", dependencies=[Depends(require("records_request"))])
def export_document_request(request_id: str, db: Session = Depends(get_db)):
    request = db.get(DocumentRequest, request_id)
    if not request:
        raise HTTPException(404, "Request not found")
    request.status = "exported"
    add_audit(
        db,
        "document_request_exported",
        "document_request",
        request.id,
        request.patient_id,
        after={"status": request.status, "recipient": request.recipient},
        meta={"note": "Demo export only; no transmission exists"},
    )
    db.commit()
    return _request_dict(request)


@router.post("/document-requests/{request_id}/match", dependencies=[Depends(require("records_request"))])
def match_document_request(request_id: str, body: MatchRequest, db: Session = Depends(get_db)):
    request = db.get(DocumentRequest, request_id)
    document = db.get(Document, body.document_id)
    if not request or not document:
        raise HTTPException(404, "Request or document not found")
    if document.patient_id != request.patient_id:
        raise HTTPException(400, "That document belongs to another patient and cannot answer this request.")
    if request.request_type == "pre_auth" and document.doc_type != "pre_auth":
        kind = str(document.doc_type or "unknown").replace("_", " ")
        raise HTTPException(
            400,
            f"A pre-authorisation request needs a pre-authorisation document. This one is a {kind}.",
        )
    request.status = "matched"
    request.matched_document_id = document.id
    add_audit(
        db,
        "document_request_matched",
        "document_request",
        request.id,
        request.patient_id,
        after={"document_id": document.id, "status": request.status},
    )
    db.commit()
    return _request_dict(request)
