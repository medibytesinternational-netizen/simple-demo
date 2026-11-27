from __future__ import annotations

from html import escape as esc

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    Draft,
    Patient,
)
from ..services.identity import require
from ..services.context import build_context
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.llm import generate_draft
from ..services import credits
from ..services.approval.f09_discharge import discharge_readiness
from .common import (
    _state,
)

router = APIRouter()


# --------------------------------------------------------------------------
# Discharge (F9)
# --------------------------------------------------------------------------
@router.get("/discharge/readiness")
def readiness(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db, encounter_id)
    result = discharge_readiness(db, patient, encounter)
    return {
        **result,
        "already_signed": state["discharge_signed"],
        "encounter_status": state["encounter"]["status"],
    }


@router.post("/discharge/generate", dependencies=[Depends(require("discharge_draft"))])
def generate_discharge(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    # Charge first, in the same transaction: a failed or refused generation rolls the charge back.
    entry = credits.charge(db, "discharge_summary", feature="F9")
    context = build_context(db, patient, encounter, state, "F9")
    content, llm_call = generate_draft(db, "F9", context)
    entry.mode = llm_call.mode
    entry.llm_call_id = llm_call.id
    draft = create_draft(db, feature="F9", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode, "latency_ms": llm_call.latency_ms}}


@router.get("/discharge/{draft_id}/print")
def discharge_print(draft_id: str, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    patient = db.get(Patient, draft.patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")
    content = draft.content or {}
    sections = content.get("sections", [])
    body = "".join(
        f"<h2>{esc(str(section.get('heading', '')))}</h2>"
        + "".join(f"<p>{esc(str(paragraph.get('text', '')))}</p>" for paragraph in section.get("paragraphs", []))
        for section in sections
    )
    meds = "".join(
        f"<tr><td>{esc(str(med.get('drug','')))}</td><td>{esc(str(med.get('dose','')))}</td>"
        f"<td>{esc(str(med.get('route','')))}</td><td>{esc(str(med.get('frequency','')))}</td>"
        f"<td>{esc(str(med.get('safety_note','') or 'clear'))}</td></tr>"
        for med in content.get("medications", [])
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Discharge summary</title>
    <style>body{{font-family:Arial;margin:40px;color:#16181d}}h1{{font-size:22px}}
    h2{{font-size:15px;margin-top:24px}}p{{font-size:13px;line-height:1.6}}
    table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e3e6eb;padding:6px;font-size:13px;text-align:left}}
    .meta{{color:#6b7280;font-size:12px}}</style></head><body>
    <h1>Discharge summary</h1>
    <div class="meta">{esc(patient.name)} · {esc(patient.mrn)} · Synthetic demo data</div>
    {body}
    <h2>Discharge medications</h2>
    <table><thead><tr><th>Drug</th><th>Dose</th><th>Route</th><th>Frequency</th><th>Safety</th></tr></thead>
    <tbody>{meds}</tbody></table>
    <p class="meta">Demo output. Not a clinical document.</p>
    </body></html>"""
    return HTMLResponse(html)


# --------------------------------------------------------------------------
# Discharge summary report, hospital format: generated from the signed record by a doctor
# (Admin, Senior or Junior), stored as a document on the timeline, viewable by everyone.
# --------------------------------------------------------------------------
from sqlalchemy import select  # noqa: E402

from ..config import settings  # noqa: E402
from ..db import utcnow  # noqa: E402
from ..models import TimelineEvent  # noqa: E402
from ..services import discharge_form  # noqa: E402
from ..services.identity import acting_name  # noqa: E402
from ..services.note_document import GENERATED_KIND  # noqa: E402
from ..services.ocr import new_document  # noqa: E402
from ..services.timeline import add_audit, add_event  # noqa: E402


@router.get("/discharge/reports")
def discharge_reports(db: Session = Depends(get_db)):
    patient, _, _ = _state(db)
    events = db.scalars(
        select(TimelineEvent)
        .where(TimelineEvent.patient_id == patient.id, TimelineEvent.type == discharge_form.REPORT_TYPE)
        .order_by(TimelineEvent.occurred_at.desc())
    ).all()
    return {"reports": [
        {"event_id": e.id, "document_id": e.document_id, "time": e.occurred_at.isoformat(), "by": e.author_name}
        for e in events
    ]}


@router.post("/discharge/report", dependencies=[Depends(require("discharge_report"))])
def discharge_report(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    form = discharge_form.build(db, patient, encounter, state)
    made_at = utcnow()
    html = discharge_form.render_html(form, made_at)
    event = add_event(
        db, patient_id=patient.id, encounter_id=encounter.id, type=discharge_form.REPORT_TYPE, subtype="F9",
        title=discharge_form.TITLE, body_text=f"Generated from {len(form['rows'])} notes on record",
        payload={"notes": len(form["rows"]), "doctor": form["doctor"]},
        source="F9", author_type="human", author_name=acting_name(), status="approved",
        occurred_at=made_at, approved_by=acting_name(),
    )
    folder = settings.uploads_dir / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{event.id}.html"
    path.write_text(html, encoding="utf-8")
    document = new_document(
        db, patient_id=patient.id, encounter_id=encounter.id,
        filename=f"{discharge_form.TITLE} {patient.mrn} {made_at:%Y-%m-%d %H%M}.html", path=str(path),
        mime="text/html", image_kind=GENERATED_KIND, doc_type=discharge_form.REPORT_TYPE,
    )
    document.ocr_status = "confirmed"
    document.confirmed_by = acting_name()
    document.confirmed_at = made_at
    event.document_id = document.id
    add_audit(db, "note_document_stored", "document", document.id, patient.id,
              after={"event_id": event.id, "doc_type": discharge_form.REPORT_TYPE})
    db.commit()
    return {"event_id": event.id, "document_id": document.id}
