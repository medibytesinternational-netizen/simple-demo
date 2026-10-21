from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Encounter
from ..services.cached.f07_icu import (
    ALL_CATEGORIES,
    assemble_entries,
    chart_for,
    missing_categories,
    shift_window,
)
from ..services.context import build_context
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.identity import acting_name, acting_user, require
from ..services.llm import generate_draft
from ..services.timeline import (
    add_audit,
    add_event,
    get_encounter,
    get_patient,
    get_state,
    list_events,
    require_open_encounter,
)

router = APIRouter()

Chart = Literal["icu", "ward"]


class ReadingRequest(BaseModel):
    category: str
    label: str
    value: str | int | float
    unit: str = ""
    device: str = ""
    recorded_at: str
    encounter_id: str | None = None


def _resolve_encounter(db: Session, encounter_id: str | None, default_icu: bool) -> Encounter:
    """The encounter to work on. A named encounter must belong to the acting patient."""
    patient = get_patient(db)
    if encounter_id:
        encounter = db.get(Encounter, encounter_id)
        if not encounter or encounter.patient_id != patient.id:
            raise HTTPException(404, "Encounter not found for this patient")
        return encounter
    if default_icu:
        icu = db.get(Encounter, "enc_icu_1")
        if icu and icu.patient_id == patient.id:
            return icu
    return get_encounter(db)


def _sheet(db: Session, encounter: Encounter, chart: str | None) -> dict[str, Any]:
    events = list_events(db, encounter.patient_id, encounter.id, limit=1000)
    entries = assemble_entries(events, encounter.ward, chart)
    return {
        "chart": chart,
        "shift_window": shift_window(entries),
        "entries": entries,
        "not_documented": missing_categories(entries, encounter.ward, chart),
    }


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _parse_time(text: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, "recorded_at must be an ISO date and time, for example 2026-10-19T06:00:00")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


@router.get("/icu/flow-sheet")
def icu_flow_sheet(encounter_id: str | None = None, chart: Chart | None = None, db: Session = Depends(get_db)):
    encounter = _resolve_encounter(db, encounter_id, default_icu=True)
    state = get_state(db, get_patient(db), encounter)
    return {"encounter": state["encounter"], **_sheet(db, encounter, chart)}


@router.post("/icu/flow-sheet/generate", dependencies=[Depends(require("clinical_draft"))])
def generate_icu_flow_sheet(
    encounter_id: str | None = None, chart: Chart | None = None, db: Session = Depends(get_db)
):
    encounter = _resolve_encounter(db, encounter_id, default_icu=True)
    patient = get_patient(db)
    state = get_state(db, patient, encounter)
    sheet = _sheet(db, encounter, chart)
    context = build_context(
        db,
        patient,
        encounter,
        state,
        "F7",
        extra={
            "icu_entries": sheet["entries"],
            "icu_shift_window": sheet["shift_window"],
            "icu_missing": sheet["not_documented"],
            "icu_chart": chart,
        },
    )
    content, llm_call = generate_draft(db, "F7", context)
    draft = create_draft(db, feature="F7", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode, "latency_ms": llm_call.latency_ms}}


@router.post("/icu/readings", dependencies=[Depends(require("record_reading"))])
def record_reading(body: ReadingRequest, db: Session = Depends(get_db)):
    encounter = _resolve_encounter(db, body.encounter_id, default_icu=False)
    require_open_encounter(encounter)
    if body.category not in ALL_CATEGORIES:
        raise HTTPException(422, f"category must be one of: {', '.join(ALL_CATEGORIES)}")
    label = body.label.strip()
    if not label:
        raise HTTPException(422, "label is required")
    value = str(body.value).strip()
    unit = body.unit.strip()
    if not value:
        raise HTTPException(422, "value is required")
    if _is_number(value) and not unit:
        raise HTTPException(422, "A numeric value needs a unit")
    recorded = _parse_time(body.recorded_at)
    recorded_text = recorded.isoformat()
    device = body.device.strip()

    for event in list_events(db, encounter.patient_id, encounter.id, limit=1000):
        payload = event.payload or {}
        if (
            event.type == "device_reading"
            and payload.get("device", "") == device
            and payload.get("label") == label
            and payload.get("recorded_at") == recorded_text
        ):
            return {"duplicate": True, "source_event_id": event.id}

    chart = chart_for(body.category, encounter.ward)
    user = acting_user()
    event = add_event(
        db,
        patient_id=encounter.patient_id,
        encounter_id=encounter.id,
        type="device_reading",
        title=f"{label} — {value} {unit}".strip(),
        body_text=f"{label}: {value} {unit} from {device or 'manual entry'}.".replace("  ", " "),
        payload={
            "category": body.category,
            "label": label,
            "value": value,
            "unit": unit,
            "recorded_at": recorded_text,
            "device": device,
            "chart": chart,
            "entered_by": acting_name(),
        },
        source="device_feed" if user.role == "integration" else "manual",
        author_type="system" if user.role == "integration" else "human",
        author_name=acting_name(),
        approved_by=acting_name(),
        occurred_at=recorded,
    )
    add_audit(
        db,
        "reading_recorded",
        "timeline_event",
        event.id,
        encounter.patient_id,
        after={"category": body.category, "label": label, "chart": chart},
    )
    db.commit()
    return {
        "duplicate": False,
        "source_event_id": event.id,
        "chart": chart,
        "encounter_id": encounter.id,
    }
