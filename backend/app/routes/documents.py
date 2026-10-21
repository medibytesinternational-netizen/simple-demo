from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..services.identity import require
from ..services.identity import acting_name
from ..config import settings
from ..db import get_db
from ..models import (
    Document,
)
from ..services.ocr import new_document, run_ocr, sample_svg
from ..services.rules import evaluate_rules
from ..services.timeline import (
    add_audit,
    event_to_dict,
)
from .common import (
    ConfirmFieldRequest,
    _doc_dict,
    _document_to_labs,
    _state,
)

router = APIRouter()


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
@router.get("/documents")
def documents_list(encounter_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Document).order_by(Document.uploaded_at.desc())
    if encounter_id:
        stmt = stmt.where(Document.encounter_id == encounter_id)
    rows = list(db.scalars(stmt))
    return {"documents": [_doc_dict(document) for document in rows]}


@router.post("/documents/upload", dependencies=[Depends(require("upload_document"))])
async def document_upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    patient, encounter, _ = _state(db)
    contents = await file.read()
    if len(contents) > 12 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 12 MB)")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", file.filename or "upload.png")
    stored = settings.uploads_dir / f"{uuid.uuid4().hex[:10]}_{safe}"
    stored.write_bytes(contents)
    document = new_document(
        db,
        patient_id=patient.id,
        encounter_id=encounter.id,
        filename=safe,
        path=str(stored),
        mime=file.content_type or "image/png",
        image_kind="file",
        doc_type="lab_report",
    )
    run_ocr(db, document)
    db.commit()
    return _doc_dict(document)


@router.get("/documents/{document_id}")
def document_detail(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    return _doc_dict(document)


@router.get("/documents/{document_id}/image")
def document_image(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    if document.image_kind == "svg":
        return Response(
            sample_svg("Ravi Menon", "MB-1001"),
            media_type="image/svg+xml",
            headers={"Cache-Control": "no-store"},
        )
    path = Path(document.path or "")
    if not path.exists():
        raise HTTPException(404, "Stored image missing")
    return FileResponse(path, media_type=document.mime or "application/octet-stream")


@router.post("/documents/{document_id}/confirm-field", dependencies=[Depends(require("confirm_document"))])
def document_confirm_field(document_id: str, body: ConfirmFieldRequest, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    extracted = document.extracted or {}
    fields = extracted.get("fields", [])
    if body.index < 0 or body.index >= len(fields):
        raise HTTPException(400, "Field index out of range")
    if body.value is not None:
        fields[body.index]["value"] = body.value
    fields[body.index]["confidence"] = 1.0
    fields[body.index]["confirmed"] = True
    document.extracted = {**extracted, "fields": [dict(field) for field in fields]}
    flag_modified(document, "extracted")
    if all(float(field.get("confidence", 1)) >= 0.8 for field in fields):
        document.ocr_status = "reviewed"
    add_audit(
        db,
        "document_field_confirmed",
        "document",
        document.id,
        document.patient_id,
        actor_name=acting_name(),
        after={"field": fields[body.index].get("name"), "value": fields[body.index].get("value")},
    )
    db.commit()
    return _doc_dict(document)


@router.post("/documents/{document_id}/commit", dependencies=[Depends(require("confirm_document"))])
def document_commit(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    labs = _document_to_labs(db, document, acting_name())
    patient, encounter, state = _state(db, document.encounter_id)
    created_alerts = evaluate_rules(db, patient, encounter, state)
    db.commit()
    return {
        "document": _doc_dict(document),
        "labs": [event_to_dict(event) for event in labs],
        "new_alerts": [{"id": alert.id, "rule_id": alert.rule_id, "title": alert.title} for alert in created_alerts],
    }
