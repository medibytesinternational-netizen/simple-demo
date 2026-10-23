from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..services import credits
from ..services.identity import acting_name, current_patient_id, require
from ..config import settings
from ..db import get_db, utcnow
from ..models import (
    Document,
    TimelineEvent,
)
from ..services.ocr import DOC_TYPES, new_document, run_ocr, sample_svg
from ..services.rules import evaluate_rules
from ..services.timeline import (
    add_audit,
    add_event,
    event_to_dict,
)
from .common import (
    ConfirmFieldRequest,
    _doc_dict,
    _state,
)

router = APIRouter()
log = logging.getLogger(__name__)

# Actor recorded when a clean lab report is saved by the upload handler rather than by a person.
AUTO_ACTOR = "system (auto)"

# PRD credit schedule: reading a lab report or prescription is "report reading";
# radiology and discharge reports are "report analysis".
CREDIT_OPERATION = {
    "lab_report": "report_reading",
    "prescription": "report_reading",
    "radiology_report": "report_analysis",
    "discharge_summary": "report_analysis",
}


class ManualFieldRequest(BaseModel):
    name: str
    value: str
    unit: str = ""
    reference_range: str = ""
    collected_at: str = ""


def _get_document(db: Session, document_id: str) -> Document:
    document = db.get(Document, document_id)
    if not document or document.patient_id != current_patient_id():
        raise HTTPException(404, "Document not found")
    return document


def _lab_flag(value: Any, reference: str) -> str:
    """high / low / normal from a range like '0.7 - 1.3', '> 90' or '< 5'; unknown when it cannot be told."""
    try:
        numeric = float(str(value).lstrip("<>").strip())
    except (TypeError, ValueError):
        return "unknown"
    text = reference.strip()
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if len(numbers) >= 2:
        low, high = numbers[0], numbers[1]
        return "low" if numeric < low else "high" if numeric > high else "normal"
    if len(numbers) == 1:
        if text.startswith(">"):
            return "normal" if numeric > numbers[0] else "low"
        if text.startswith("<"):
            return "normal" if numeric < numbers[0] else "high"
    return "unknown"


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
@router.get("/documents")
def documents_list(encounter_id: str | None = None, db: Session = Depends(get_db)):
    stmt = (
        select(Document)
        .where(Document.patient_id == current_patient_id())
        .order_by(Document.uploaded_at.desc())
    )
    if encounter_id:
        stmt = stmt.where(Document.encounter_id == encounter_id)
    rows = list(db.scalars(stmt))
    return {
        "documents": [
            {**_doc_dict(document), "field_count": len((document.extracted or {}).get("fields", []))}
            for document in rows
        ]
    }


@router.post("/documents/upload", dependencies=[Depends(require("upload_document"))])
async def document_upload(
    file: UploadFile = File(...),
    doc_type: str = Form("lab_report"),
    db: Session = Depends(get_db),
):
    if doc_type not in DOC_TYPES:
        raise HTTPException(400, f"Document type must be one of: {', '.join(DOC_TYPES)}")
    patient, encounter, _ = _state(db)
    contents = await file.read()
    if len(contents) > 12 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 12 MB)")
    credits.charge(db, CREDIT_OPERATION[doc_type], feature="F8")
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
        doc_type=doc_type,
    )
    run_ocr(db, document)
    # Persist the document, the OCR audit entry and the credit charge first. If the auto-commit below
    # fails, this is the state the document is left in (reviewed, nothing on the timeline).
    db.commit()
    outcome: dict[str, Any] = {
        "auto_committed": False,
        "auto_commit_error": None,
        "labs": [],
        "events": [],
        "new_alerts": [],
    }
    if document.doc_type == "lab_report" and document.ocr_status == "reviewed":
        document_id, patient_id = document.id, document.patient_id
        try:
            events, alerts = _commit_and_evaluate(db, document, AUTO_ACTOR, auto=True)
            db.commit()
        except Exception as exc:  # the upload itself must still succeed
            db.rollback()
            log.warning("Auto-commit of document %s failed: %s", document_id, exc)
            message = str(getattr(exc, "detail", None) or exc) or exc.__class__.__name__
            outcome["auto_commit_error"] = message
            add_audit(
                db,
                "document_auto_commit_failed",
                "document",
                document_id,
                patient_id,
                actor_type="system",
                actor_name=AUTO_ACTOR,
                after={"error": message},
                meta={"trigger": "upload"},
            )
            db.commit()
        else:
            dicts = [event_to_dict(event) for event in events]
            outcome.update(
                auto_committed=True,
                labs=dicts,
                events=dicts,
                new_alerts=[{"id": a.id, "rule_id": a.rule_id, "title": a.title} for a in alerts],
            )
    return {**_doc_dict(document), **outcome}


@router.get("/documents/{document_id}")
def document_detail(document_id: str, db: Session = Depends(get_db)):
    return _doc_dict(_get_document(db, document_id))


@router.get("/documents/{document_id}/image")
def document_image(document_id: str, db: Session = Depends(get_db)):
    document = _get_document(db, document_id)
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
    document = _get_document(db, document_id)
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


@router.post("/documents/{document_id}/fields", dependencies=[Depends(require("confirm_document"))])
def document_add_field(document_id: str, body: ManualFieldRequest, db: Session = Depends(get_db)):
    """A person types a value read from the original; it is stored as confirmed and marked manual."""
    document = _get_document(db, document_id)
    if document.ocr_status == "confirmed":
        raise HTTPException(409, "This document is already on the timeline")
    name, value = body.name.strip(), body.value.strip()
    if not name or not value:
        raise HTTPException(400, "A name and a value are both needed")
    extracted = document.extracted or {}
    fields = [dict(field) for field in extracted.get("fields", [])]
    collected = body.collected_at.strip() or (document.uploaded_at or utcnow()).date().isoformat()
    fields.append(
        {
            "name": name,
            "value": value,
            "unit": body.unit.strip(),
            "reference_range": body.reference_range.strip(),
            "collected_at": collected,
            "confidence": 1.0,
            "page": None,
            "confirmed": True,
            "manual": True,
        }
    )
    document.extracted = {**extracted, "document_type": document.doc_type, "fields": fields}
    flag_modified(document, "extracted")
    document.ocr_status = (
        "reviewed" if all(float(field.get("confidence", 1)) >= 0.8 for field in fields) else "needs_confirmation"
    )
    add_audit(
        db,
        "document_field_entered",
        "document",
        document.id,
        document.patient_id,
        actor_name=acting_name(),
        after={"field": name, "value": value, "manual": True},
    )
    db.commit()
    return _doc_dict(document)


def _commit_document(db: Session, document: Document, actor: str, *, auto: bool = False) -> list[TimelineEvent]:
    """Write the confirmed fields to the timeline as the event type that matches the document.

    ``auto`` is the upload handler saving a clean lab report: the author and audit actor are the
    system, not a person, and a single ``document_auto_committed`` entry replaces ``document_confirmed``.
    """
    if document.ocr_status == "confirmed":
        raise HTTPException(409, "This document is already on the timeline")
    fields = (document.extracted or {}).get("fields", [])
    if not fields:
        raise ValueError("Nothing to commit. Type the values from the original first.")
    pending = [field for field in fields if float(field.get("confidence", 1)) < 0.8]
    if pending:
        raise ValueError(
            "Confirm low-confidence fields before committing: "
            + ", ".join(str(field.get("name")) for field in pending)
        )
    doc_type = document.doc_type or "lab_report"
    common = dict(
        patient_id=document.patient_id,
        encounter_id=document.encounter_id,
        source="F8",
        author_type="system" if auto else "human",
        author_name=actor,
        document_id=document.id,
    )
    audit_actor: dict[str, Any] = {"actor_type": "system", "actor_name": actor} if auto else {}
    created: list[TimelineEvent] = []
    if doc_type == "prescription":
        for field in fields:
            drug, dose, frequency = field.get("name"), field.get("value"), field.get("reference_range", "")
            created.append(
                add_event(
                    db,
                    type="med_order",
                    title=f"Home medication - {drug} {dose} {frequency}".strip(),
                    body_text=f"{drug} {dose} {frequency} (home, active); from {document.filename}.".replace("  ", " "),
                    payload={
                        "drug": drug,
                        "dose": dose,
                        "frequency": frequency,
                        "route": "",
                        "kind": "home",
                        "status": "active",
                        "indication": "",
                        "document_id": document.id,
                        "confidence": 1.0,
                    },
                    **common,
                )
            )
    elif doc_type in ("radiology_report", "discharge_summary"):
        label = doc_type.replace("_", " ").capitalize()
        created.append(
            add_event(
                db,
                type="document_review",
                title=f"{label} reviewed - {document.filename}",
                body_text="\n".join(f"{field.get('name')}: {field.get('value')}" for field in fields),
                payload={
                    "document_type": doc_type,
                    "filename": document.filename,
                    "fields": [dict(field) for field in fields],
                    "document_id": document.id,
                    "review_status": "reviewed",
                },
                **common,
            )
        )
    else:
        for field in fields:
            value = field.get("value")
            reference = str(field.get("reference_range", ""))
            unit = field.get("unit", "")
            created.append(
                add_event(
                    db,
                    type="lab_result",
                    title=f"{field.get('name')} — {value} {unit}".strip(),
                    body_text=f"{field.get('name')}: {value} {unit} (reference {reference}); confirmed from {document.filename}.",
                    payload={
                        "name": field.get("name"),
                        "value": value,
                        "unit": unit,
                        "reference_range": reference,
                        "flag": _lab_flag(value, reference),
                        # Confirming a field is a transcription check, not a clinician's review of the result.
                        "review_status": "unreviewed",
                        "collected_at": field.get("collected_at", ""),
                        "document_id": document.id,
                        "confidence": 1.0,
                    },
                    **common,
                )
            )
    document.ocr_status = "confirmed"
    document.confirmed_by = actor
    document.confirmed_at = utcnow()
    add_audit(
        db,
        "document_auto_committed" if auto else "document_confirmed",
        "document",
        document.id,
        document.patient_id,
        actor_name=actor,
        after={"events_created": [event.id for event in created], "doc_type": doc_type},
        **({"actor_type": "system", "meta": {"trigger": "upload", "uploaded_by": document.uploaded_by}} if auto else {}),
    )
    for event in created:
        add_audit(
            db,
            "timeline_committed",
            "timeline_event",
            event.id,
            document.patient_id,
            after={"type": event.type, "title": event.title, "source": "F8"},
            **audit_actor,
        )
    return created


def _commit_and_evaluate(
    db: Session, document: Document, actor: str, *, auto: bool = False
) -> tuple[list[TimelineEvent], list[Any]]:
    """The one commit path: write the events, then re-run the safety rules. The caller commits the session."""
    events = _commit_document(db, document, actor, auto=auto)
    patient, encounter, state = _state(db, document.encounter_id)
    return events, evaluate_rules(db, patient, encounter, state)


@router.post("/documents/{document_id}/commit", dependencies=[Depends(require("confirm_document"))])
def document_commit(document_id: str, db: Session = Depends(get_db)):
    document = _get_document(db, document_id)
    events, created_alerts = _commit_and_evaluate(db, document, acting_name())
    db.commit()
    dicts = [event_to_dict(event) for event in events]
    return {
        "document": _doc_dict(document),
        "labs": dicts if (document.doc_type or "lab_report") == "lab_report" else [],
        "events": dicts,
        "new_alerts": [{"id": alert.id, "rule_id": alert.rule_id, "title": alert.title} for alert in created_alerts],
    }
