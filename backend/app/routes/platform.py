"""Shared platform routes: who can act, which patients exist, and AI credits."""

from __future__ import annotations

import re

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..models import Encounter, Patient
from ..config import settings
from ..services import credits, intake, pipeline
from ..services.context import create_transcript_event
from ..services.drafts import create_draft
from ..services.ocr import new_document, run_ocr
from ..services.identity import DIRECTORY, PERMISSIONS, USERS, acting_name, acting_user, require
from ..services.timeline import add_audit, add_event, new_id

router = APIRouter()


class PackRequest(BaseModel):
    size: int


class PatientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    age: int = Field(ge=0, le=130)
    sex: str = Field(min_length=1, max_length=20)
    phone: str | None = None
    allergies: list[str] = Field(default_factory=list)
    no_known_allergies: bool = False
    problems: list[str] = Field(default_factory=list)
    # Recording / document read at intake: attached to the new patient once registered.
    intake_ids: list[str] = Field(default_factory=list)


def user_dict(user) -> dict:
    return {"id": user.id, "name": user.name, "role": user.role, "home": user.home}


def allowed_actions(user=None) -> list[str]:
    role = (user or acting_user()).role
    return sorted(action for action, roles in PERMISSIONS.items() if role in roles)


@router.get("/users")
def users():
    return {"users": [user_dict(user) for user in USERS], "acting": user_dict(acting_user())}


@router.get("/patients")
def patients(db: Session = Depends(get_db)):
    rows = db.scalars(select(Patient).order_by(Patient.name)).all()
    encounters = db.scalars(select(Encounter).order_by(Encounter.admitted_at.desc())).all()
    latest: dict[str, Encounter] = {}
    for encounter in encounters:
        latest.setdefault(encounter.patient_id, encounter)
    return {
        "patients": [
            {
                "id": patient.id,
                "mrn": patient.mrn,
                "name": patient.name,
                "age": patient.age,
                "sex": patient.sex,
                "ward": latest[patient.id].ward if patient.id in latest else None,
                "bed": latest[patient.id].bed if patient.id in latest else None,
                "encounter_status": latest[patient.id].status if patient.id in latest else None,
            }
            for patient in rows
        ]
    }


def _next_mrn(db: Session) -> str:
    numbers = [int(m.group(1)) for mrn in db.scalars(select(Patient.mrn)) if (m := re.fullmatch(r"MB-(\d+)", mrn or ""))]
    return f"MB-{max(numbers, default=1000) + 1}"


@router.post("/patients", dependencies=[Depends(require("register_patient"))])
def register_patient(body: PatientCreate, db: Session = Depends(get_db)):
    """Register a patient and open an OPD visit, so recordings and documents have a home."""
    name = " ".join(body.name.split())
    allergies = [a.strip() for a in body.allergies if a.strip()]
    for intake_id in dict.fromkeys(body.intake_ids):
        try:
            meta = intake.load(intake_id)
        except KeyError:
            raise HTTPException(404, f"Intake {intake_id} not found") from None
        if meta.get("attached_to"):
            raise HTTPException(409, "That recording or document is already attached to a patient")
        if meta["status"] != "ready":
            raise HTTPException(409, "Wait until the recording or document has been read")
    if allergies and body.no_known_allergies:
        raise HTTPException(422, "Choose either the listed allergies or no known drug allergies, not both")
    if not allergies and not body.no_known_allergies:
        raise HTTPException(422, "Record the allergies or confirm no known drug allergies")
    duplicate = db.scalars(
        select(Patient).where(func.lower(Patient.name) == name.lower(), Patient.age == body.age)
    ).first()
    if duplicate:
        raise HTTPException(409, f"{duplicate.name} ({duplicate.mrn}) is already registered with this age")

    patient = Patient(
        id=new_id("pat"),
        mrn=_next_mrn(db),
        name=name,
        age=body.age,
        sex=body.sex,
        allergies=allergies,
        problems=[p.strip() for p in body.problems if p.strip()],
    )
    encounter = Encounter(
        id=new_id("enc"),
        patient_id=patient.id,
        kind="OPD",
        ward="OPD",
        attending=acting_name(),
        admitted_at=utcnow(),
        status="active",
    )
    db.add_all([patient, encounter])
    db.flush()
    allergy_text = ", ".join(allergies) if allergies else "No known drug allergies"
    event = add_event(
        db,
        patient_id=patient.id,
        encounter_id=encounter.id,
        type="registration",
        title=f"Registered {patient.name} ({patient.mrn}), OPD visit opened",
        body_text=f"{patient.age} y, {patient.sex}. Allergies: {allergy_text}.",
        payload={
            "mrn": patient.mrn,
            "age": patient.age,
            "sex": patient.sex,
            "phone": body.phone or "",
            "allergies": allergies,
            "no_known_allergies": body.no_known_allergies,
            "problems": patient.problems,
            "visit": "OPD",
        },
        source="registration",
        approved_by=acting_name(),
    )
    add_audit(db, "patient_registered", "patient", patient.id, patient.id, after={"mrn": patient.mrn, "encounter_id": encounter.id, "event_id": event.id})
    attached = [_attach_intake(db, patient, encounter, intake_id) for intake_id in dict.fromkeys(body.intake_ids)]
    db.commit()
    return {
        "patient": {"id": patient.id, "mrn": patient.mrn, "name": patient.name, "age": patient.age, "sex": patient.sex, "allergies": allergies},
        "encounter": {"id": encounter.id, "kind": encounter.kind, "status": encounter.status},
        "attached": attached,
    }


# --------------------------------------------------------------------------
# Intake: read details from the recording or an old prescription before registering
# --------------------------------------------------------------------------
INTAKE_DOC_BYTES = 12 * 1024 * 1024
INTAKE_AUDIO_BYTES = 64 * 1024 * 1024


def _intake_out(meta: dict) -> dict:
    return {
        "intake_id": meta["id"],
        "kind": meta["kind"],
        "filename": meta["filename"],
        "status": meta["status"],
        "fields": meta.get("fields") or {},
        "method": meta.get("method"),
        "error": meta.get("error"),
        "doc_type": meta.get("doc_type"),
        "preview": meta.get("preview"),
        "values": meta.get("values") or [],
    }


@router.post("/intake/document", dependencies=[Depends(require("register_patient"))])
async def intake_document(file: UploadFile = File(...), doc_type: str = Form("auto"), db: Session = Depends(get_db)):
    """An old prescription or discharge summary: read the patient's details from it."""
    if doc_type != "auto" and doc_type not in intake.DOC_TYPES:
        raise HTTPException(422, "Unknown document type")
    contents = await file.read(INTAKE_DOC_BYTES + 1)
    if len(contents) > INTAKE_DOC_BYTES:
        raise HTTPException(413, "File too large (max 12 MB)")
    if not contents:
        raise HTTPException(400, "The file is empty")
    mime = file.content_type or "application/octet-stream"
    name = (file.filename or "document").lower()
    is_image = mime.startswith("image/")
    if not (is_image or mime == "application/pdf" or name.endswith(".pdf")):
        raise HTTPException(415, "Upload a PDF or a photo of the document")
    credits.charge(db, "report_reading", feature="F8", mode=settings.effective_llm_mode)
    meta = intake.create("document", file.filename or "document", mime, contents, doc_type=doc_type)
    text = intake.document_text(Path(meta["path"]), mime)
    if doc_type == "auto":
        # No type is asked for: a page of medicines is a prescription, anything else a discharge summary.
        doc_type = meta["doc_type"] = intake.guess_doc_type(text, file.filename or "")
    fields, method = intake.extract("document", text, (contents, mime) if is_image else None)
    from ..services.ocr import parse_report

    values = parse_report(doc_type, [text] if text else [], utcnow().date().isoformat()).get("fields", []) if text else []
    meta.update(status="ready", fields=fields, method=method, text_found=bool(text),
                values=[{"name": v.get("name"), "value": v.get("value"), "unit": v.get("unit", ""),
                         "reference_range": v.get("reference_range", "")} for v in values])
    if not fields:
        meta["error"] = "No details could be read. Type them in the form; the document is still attached."
    intake.save(meta)
    add_audit(db, "intake_document_read", "intake", meta["id"], None, after={"fields": sorted(fields), "method": method, "doc_type": doc_type})
    db.commit()
    return _intake_out(meta)


@router.post("/intake/audio", dependencies=[Depends(require("register_patient"))])
async def intake_audio(file: UploadFile = File(...), consent: bool = Form(False), db: Session = Depends(get_db)):
    """The consultation recording, taken with consent before registration. It pre-fills the form now
    and becomes the OPD draft once the patient is registered."""
    from .notes import _looks_like_audio

    if not consent:
        raise HTTPException(403, "Record the patient's consent before capturing audio")
    if not _looks_like_audio(file.filename, file.content_type):
        raise HTTPException(415, "That file is not audio. Upload mp3, wav, m4a, webm or ogg.")
    contents = await file.read(INTAKE_AUDIO_BYTES + 1)
    if len(contents) > INTAKE_AUDIO_BYTES:
        raise HTTPException(413, "Audio too large (max 64 MB)")
    if not contents:
        raise HTTPException(400, "The audio file is empty")
    if not pipeline.configured():
        raise HTTPException(400, "Voice notes need the MediBytes pipeline; set OPENAI_API_KEY")
    credits.charge(db, "voice_note", feature="F1", mode="live")
    meta = intake.create(
        "audio", file.filename or "consultation.webm", file.content_type or "audio/webm", contents,
        consent_by=acting_name(), consent_at=utcnow().isoformat(),
    )
    pipeline.submit(contents, meta["filename"], meta["mime"], meta["id"])
    meta["status"] = "running"
    intake.save(meta)
    add_audit(db, "intake_audio_submitted", "intake", meta["id"], None, actor_type="model", actor_name="MediBytes pipeline", after={"consent_by": meta["consent_by"]})
    db.commit()
    return _intake_out(meta)


@router.get("/intake/{intake_id}", dependencies=[Depends(require("register_patient"))])
def intake_status(intake_id: str):
    try:
        meta = intake.load(intake_id)
    except KeyError:
        raise HTTPException(404, "Intake not found") from None
    if meta["kind"] == "audio" and meta["status"] == "running":
        result = pipeline.fetch(intake_id) or {}
        job = result.get("job_status")
        if job == "failed":
            meta.update(status="failed", error=result.get("job_error") or "The recording could not be processed")
        elif job == "succeeded":
            text = str(result.get("transcript") or "").strip()
            note = result.get("note") or {}
            if not text or not pipeline.has_items(note):
                meta.update(status="failed", error="No speech was detected in the recording")
            else:
                fields, method = intake.extract("audio", text)
                # The OPD report, shown right away; it is saved (with citations) only at registration.
                preview = pipeline.draft_content("F1", note, "", [])
                meta.update(status="ready", transcript=text, note=note, fields=fields, method=method, preview=preview)
        intake.save(meta)
    return _intake_out(meta)


def _attach_intake(db: Session, patient: Patient, encounter: Encounter, intake_id: str) -> dict:
    """Give the new patient what was captured at intake."""
    meta = intake.load(intake_id)
    if meta["kind"] == "document":
        document = new_document(
            db, patient_id=patient.id, encounter_id=encounter.id, filename=meta["filename"],
            path=meta["path"], mime=meta["mime"], doc_type=meta["doc_type"],
        )
        run_ocr(db, document)
        out = {"intake_id": intake_id, "kind": "document", "document_id": document.id}
    else:
        consent_by = meta.get("consent_by") or acting_name()
        add_event(
            db, patient_id=patient.id, encounter_id=encounter.id, type="consent",
            title="Consent for consultation capture",
            body_text=f"Granted before the recording at registration; recorded by {consent_by}.",
            payload={"consent_type": "consultation_capture", "granted": True, "note": "Given at registration, before recording"},
            source="consent", approved_by=consent_by,
        )
        event = create_transcript_event(db, patient, encounter, "F1", meta["transcript"], "Consultation (MediBytes pipeline)")
        event.payload = {**(event.payload or {}), "audio_id": intake_id, "pipeline_note": meta["note"]}
        content = pipeline.draft_content("F1", meta["note"], event.id, event.payload.get("segments") or [])
        draft = create_draft(db, feature="F1", patient=patient, encounter=encounter, content=content, llm_call=None, created_from_event_ids=[event.id])
        out = {"intake_id": intake_id, "kind": "audio", "draft_id": draft.id}
    meta["attached_to"] = patient.id
    intake.save(meta)
    add_audit(db, "intake_attached", "intake", intake_id, patient.id, after=out)
    return out


@router.get("/credits")
def credit_status(db: Session = Depends(get_db)):
    return credits.status(db)


@router.post("/credits/packs", dependencies=[Depends(require("buy_credits"))])
def credit_pack(body: PackRequest, db: Session = Depends(get_db)):
    result = credits.add_pack(db, body.size)
    db.commit()
    return result


__all__ = ["router", "allowed_actions", "user_dict", "DIRECTORY"]
