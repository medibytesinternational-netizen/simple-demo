from __future__ import annotations


from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..services.identity import require
from ..db import get_db
from ..models import (
    Encounter,
)
from ..services.context import build_context
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.llm import generate_draft
from .common import (
    _state,
)

router = APIRouter()


def _icu_encounter_id(db: Session, encounter_id: str | None) -> str | None:
    if encounter_id and db.get(Encounter, encounter_id):
        return encounter_id
    icu = db.get(Encounter, "enc_icu_1")
    return icu.id if icu else None


@router.get("/icu/flow-sheet")
def icu_flow_sheet(encounter_id: str | None = None, db: Session = Depends(get_db)):
    resolved = _icu_encounter_id(db, encounter_id)
    _, _, state = _state(db, resolved)
    return {
        "encounter": state["encounter"],
        "shift_window": state.get("icu_shift_window", {}),
        "entries": state.get("icu_entries", []),
    }


@router.post("/icu/flow-sheet/generate", dependencies=[Depends(require("clinical_draft"))])
def generate_icu_flow_sheet(encounter_id: str | None = None, db: Session = Depends(get_db)):
    resolved = _icu_encounter_id(db, encounter_id)
    patient, encounter, state = _state(db, resolved)
    context = build_context(db, patient, encounter, state, "F7")
    content, llm_call = generate_draft(db, "F7", context)
    draft = create_draft(db, feature="F7", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode, "latency_ms": llm_call.latency_ms}}
