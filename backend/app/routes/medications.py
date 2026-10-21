from __future__ import annotations


from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.identity import require
from ..services.context import build_context
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.llm import generate_draft
from ..services.revenue import reconciliation
from .common import (
    _state,
)

router = APIRouter()


@router.get("/medications")
def medications(encounter_id: str | None = None, db: Session = Depends(get_db)):
    _, _, state = _state(db, encounter_id)
    return {
        "home_medications": state["home_meds"],
        "current_medications": state["active_meds"],
    }


@router.get("/medications/reconciliation")
def medication_reconciliation(encounter_id: str | None = None, db: Session = Depends(get_db)):
    _, _, state = _state(db, encounter_id)
    return reconciliation(state)


@router.post("/medications/reconciliation/generate", dependencies=[Depends(require("reconcile"))])
def generate_reconciliation(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    recon = reconciliation(state)
    context = build_context(db, patient, encounter, state, "F6", extra={"reconciliation": recon})
    content, llm_call = generate_draft(db, "F6", context)
    draft = create_draft(db, feature="F6", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "reconciliation": recon, "llm": {"mode": llm_call.mode}}
