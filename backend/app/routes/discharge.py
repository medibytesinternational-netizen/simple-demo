from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    Draft,
)
from ..services.context import build_context
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.llm import generate_draft
from ..services.timeline import (
    list_events,
)
from .common import (
    _state,
)

router = APIRouter()


# --------------------------------------------------------------------------
# Discharge (F9)
# --------------------------------------------------------------------------
@router.get("/discharge/readiness")
def discharge_readiness(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db, encounter_id)
    events = list_events(db, patient.id, encounter.id, approved_only=True, limit=1000)
    types = {event.type for event in events}
    required = [
        ("consult_note", "Consultation note", "F1"),
        ("admission_note", "Admission assessment", "F2"),
        ("round_note", "Round handover", "F3"),
        ("lab_result", "Laboratory results", "Labs"),
        ("procedure", "Procedures documented", "Care"),
    ]
    items = [
        {
            "key": key,
            "label": label,
            "present": key in types,
            "source": source,
        }
        for key, label, source in required
    ]
    return {
        "items": items,
        "ready": all(item["present"] for item in items),
        "already_signed": state["discharge_signed"],
        "encounter_status": state["encounter"]["status"],
    }


@router.post("/discharge/generate")
def generate_discharge(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    context = build_context(db, patient, encounter, state, "F9")
    content, llm_call = generate_draft(db, "F9", context)
    draft = create_draft(db, feature="F9", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode, "latency_ms": llm_call.latency_ms}}


@router.get("/discharge/{draft_id}/print")
def discharge_print(draft_id: str, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    content = draft.content or {}
    sections = content.get("sections", [])
    body = "".join(
        f"<h2>{section.get('heading', '')}</h2>"
        + "".join(f"<p>{paragraph.get('text', '')}</p>" for paragraph in section.get("paragraphs", []))
        for section in sections
    )
    meds = "".join(
        f"<tr><td>{med.get('drug','')}</td><td>{med.get('dose','')}</td>"
        f"<td>{med.get('route','')}</td><td>{med.get('frequency','')}</td>"
        f"<td>{med.get('safety_note','') or 'clear'}</td></tr>"
        for med in content.get("medications", [])
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Discharge summary</title>
    <style>body{{font-family:Arial;margin:40px;color:#16181d}}h1{{font-size:22px}}
    h2{{font-size:15px;margin-top:24px}}p{{font-size:13px;line-height:1.6}}
    table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e3e6eb;padding:6px;font-size:13px;text-align:left}}
    .meta{{color:#6b7280;font-size:12px}}</style></head><body>
    <h1>Discharge summary</h1>
    <div class="meta">Ravi Menon · MB-1001 · Synthetic demo data</div>
    {body}
    <h2>Discharge medications</h2>
    <table><thead><tr><th>Drug</th><th>Dose</th><th>Route</th><th>Frequency</th><th>Safety</th></tr></thead>
    <tbody>{meds}</tbody></table>
    <p class="meta">Demo output. Not a clinical document.</p>
    </body></html>"""
    return HTMLResponse(html)
