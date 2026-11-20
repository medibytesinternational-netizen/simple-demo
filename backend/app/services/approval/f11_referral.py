from __future__ import annotations

from typing import Any

from ...db import utcnow
from ...models import Referral
from ..timeline import new_id
from ..cached.f11_referral import PLACEHOLDER_QUESTION
from . import ApprovalContext, after_event, payload_builder, validator


@validator("F11")
def refuse_placeholder_question(ctx: ApprovalContext) -> None:
    if ctx.payload.get("format") == "referral_v2":
        from ..referral_form import missing

        gaps = missing(ctx.payload)
        if gaps:
            raise ValueError("Fill these before approving the referral: " + ", ".join(gaps) + ".")
        return
    question = ctx.payload.get("question") or {}
    text = question.get("text", "") if isinstance(question, dict) else str(question)
    if not text.strip() or " ".join(text.split()).casefold() == PLACEHOLDER_QUESTION.casefold():
        raise ValueError("Write the referral question before approving; it is still the placeholder.")


@payload_builder("F11")
def create_referral(ctx: ApprovalContext, event_payload: dict[str, Any]) -> None:
    payload, patient, encounter, draft = ctx.payload, ctx.patient, ctx.encounter, ctx.draft
    question = payload.get("question") or {}
    history = payload.get("history") or {}
    if payload.get("format") == "referral_v2":
        from ..progress import signature
        from ..referral_form import URGENCY

        text = lambda v: str((v or {}).get("text") or "").strip()
        details = [text(c) for c in payload.get("salient_details") or [] if text(c)]
        heard = [text(c) for c in payload.get("salient_details") or [] if text(c) and c.get("origin") != "record"]
        # Doctor's name and signature, date and time: whoever approves, when they approve.
        stamp = {"signed_by": signature(), "signed_at": utcnow().isoformat()}
        event_payload.update(stamp)
        ctx.payload.update(stamp)
        referral = Referral(
            id=new_id("ref"), patient_id=patient.id, encounter_id=encounter.id,
            specialty=text(payload.get("department")) or "Specialist service",
            specialist=text(payload.get("unit_chief")),
            question="; ".join(heard or details), history="; ".join(d for d in details if d not in heard),
            urgency=URGENCY.get(payload.get("referral_type") or "", "routine"),
            status="queued", draft_id=draft.id, approved_by=ctx.approver, created_at=utcnow(),
        )
        ctx.db.add(referral)
        ctx.db.flush()
        event_payload["referral_id"] = referral.id
        return
    referral = Referral(
        id=new_id("ref"),
        patient_id=patient.id,
        encounter_id=encounter.id,
        specialty=payload.get("specialty", "Specialist service"),
        specialist=payload.get("specialist", ""),
        question=question.get("text", "") if isinstance(question, dict) else str(question),
        history=history.get("text", "") if isinstance(history, dict) else str(history),
        urgency=payload.get("urgency", "routine"),
        status="queued",
        draft_id=draft.id,
        approved_by=ctx.approver,
        created_at=utcnow(),
    )
    ctx.db.add(referral)
    ctx.db.flush()
    event_payload["referral_id"] = referral.id


@after_event("F11")
def store_referral_form(ctx: ApprovalContext, event) -> None:
    """The approved referral form, stored so the timeline can open and print it."""
    if ctx.payload.get("format") != "referral_v2":
        return
    from ...config import settings
    from ..note_document import GENERATED_KIND
    from ..ocr import new_document
    from ..referral_form import REFERRAL_DOC_TYPE, render_html
    from ..timeline import add_audit

    folder = settings.uploads_dir / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{event.id}.html"
    path.write_text(render_html({**ctx.payload, **(event.payload or {})}), encoding="utf-8")
    now = utcnow()
    document = new_document(
        ctx.db, patient_id=ctx.patient.id, encounter_id=ctx.encounter.id,
        filename=f"Referral {ctx.patient.mrn} {now:%Y-%m-%d %H%M}.html", path=str(path), mime="text/html",
        image_kind=GENERATED_KIND, doc_type=REFERRAL_DOC_TYPE,
    )
    document.ocr_status = "confirmed"
    document.confirmed_by = ctx.approver
    document.confirmed_at = now
    event.document_id = document.id
    add_audit(ctx.db, "note_document_stored", "document", document.id, ctx.patient.id,
              actor_name=ctx.approver, after={"event_id": event.id, "doc_type": REFERRAL_DOC_TYPE})
