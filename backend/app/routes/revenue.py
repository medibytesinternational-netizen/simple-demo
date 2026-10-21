from __future__ import annotations


from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..models import (
    ClaimReview,
)
from ..services.identity import require
from ..services.context import build_context
from ..services.drafts import (
    create_draft,
    draft_to_dict,
)
from ..services.llm import generate_draft
from ..services.revenue import claim_pack_html, claim_prep, leakage
from ..services.timeline import (
    add_audit,
    new_id,
)
from .common import (
    _state,
)

router = APIRouter()


# --------------------------------------------------------------------------
# Revenue (F12, F13)
# --------------------------------------------------------------------------
@router.get("/revenue/claim-prep")
def revenue_claim_prep(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db, encounter_id)
    prep = claim_prep(db, patient, encounter, state)
    reviews = list(
        db.scalars(
            select(ClaimReview)
            .where(ClaimReview.encounter_id == encounter.id)
            .order_by(ClaimReview.created_at.desc())
        )
    )
    return {
        **prep,
        "reviews": [
            {
                "id": review.id,
                "status": review.status,
                "prepared_at": review.prepared_at.isoformat() if review.prepared_at else None,
                "reviewed_by": review.reviewed_by,
            }
            for review in reviews
        ],
    }


@router.post("/revenue/claim-prep/prepare", dependencies=[Depends(require("revenue_work"))])
def prepare_claim(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    prep = claim_prep(db, patient, encounter, state)
    review = ClaimReview(
        id=new_id("clm"),
        patient_id=patient.id,
        encounter_id=encounter.id,
        status=prep["status"],
        prepared_at=utcnow(),
        created_at=utcnow(),
    )
    db.add(review)
    add_audit(
        db,
        "claim_pack_prepared",
        "claim_review",
        review.id,
        patient.id,
        after={
            "status": review.status,
            "missing_documents": [item["label"] for item in prep["missing_documents"]],
            "unbilled": [item["procedure"] for item in prep["unbilled_procedures"]],
            "underbilled": [item["description"] for item in prep.get("underbilled_items", [])],
            "contradictions": [item["title"] for item in prep.get("contradictions", [])],
            "tpa_review": prep.get("tpa_review", {}),
            "total_amount": prep["total_amount"],
            "expected_total_amount": prep.get("expected_total_amount", prep["total_amount"]),
        },
        meta={"note": "Review queue only; no submission"},
    )
    db.commit()
    return {"review": {"id": review.id, "status": review.status}, "prep": prep}


@router.get("/revenue/claim-prep/pack.html")
def claim_pack(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db, encounter_id)
    prep = claim_prep(db, patient, encounter, state)
    return HTMLResponse(claim_pack_html(patient, encounter, prep))


@router.post("/revenue/claim-prep/explain", dependencies=[Depends(require("revenue_work"))])
def explain_claim(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    prep = claim_prep(db, patient, encounter, state)
    leak = leakage(db, patient, encounter, state)
    context = build_context(
        db,
        patient,
        encounter,
        state,
        "F12",
        extra={"revenue": {**prep, **leak}},
    )
    content, llm_call = generate_draft(db, "F12", context)
    draft = create_draft(db, feature="F12", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode}}


@router.get("/revenue/leakage")
def revenue_leakage(encounter_id: str | None = None, db: Session = Depends(get_db)):
    patient, encounter, state = _state(db, encounter_id)
    return leakage(db, patient, encounter, state)


@router.post("/revenue/leakage/explain", dependencies=[Depends(require("revenue_work"))])
def explain_leakage(db: Session = Depends(get_db)):
    patient, encounter, state = _state(db)
    leak = leakage(db, patient, encounter, state)
    context = build_context(db, patient, encounter, state, "F13", extra={"revenue": leak})
    content, llm_call = generate_draft(db, "F13", context)
    draft = create_draft(db, feature="F13", patient=patient, encounter=encounter, content=content, llm_call=llm_call)
    db.commit()
    return {"draft": draft_to_dict(draft), "llm": {"mode": llm_call.mode}}
