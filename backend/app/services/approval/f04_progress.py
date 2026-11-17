from __future__ import annotations

from sqlalchemy import select

from ...db import utcnow
from ...models import InvestigationRequest
from . import ApprovalContext, after_event, payload_builder, validator


@validator("F4")
def require_exam_and_plan(ctx: ApprovalContext) -> None:
    payload = ctx.payload
    if payload.get("format") == "progress_v2":
        # A daily progress-notes row: only the notes as dictated, signed by who dictated them.
        if not [n for n in payload.get("notes") or [] if str((n or {}).get("text") or "").strip()]:
            raise ValueError("Nothing was heard in this progress note.")
        return
    exam = (payload.get("exam") or {}).get("general") or {}
    plan = payload.get("plan") or {}
    if not str(exam.get("text", "")).strip() or not str(plan.get("text", "")).strip():
        raise ValueError(
            "F4 cannot be approved: the examination and plan are required. "
            "Edit the draft to document them first."
        )
    # A model may never write the examination or plan that gets signed.
    if not exam.get("human_authored") or not plan.get("human_authored"):
        raise ValueError(
            "F4 cannot be approved: the examination and plan must be written by the clinician, "
            "not generated."
        )


@payload_builder("F4")
def stamp_signature(ctx: ApprovalContext, payload: dict) -> None:
    if payload.get("format") != "progress_v2":
        return
    from ..progress import signature

    payload["signed_by"] = signature()
    payload["signed_at"] = utcnow().isoformat()


OPEN_REQUEST = ("requested", "approved")


@after_event("F4")
def raise_investigation_requests(ctx: ApprovalContext, event) -> None:
    """A doctor's progress note that asks for a scan or report raises a request for it."""
    raise_requests_for_note(ctx.db, event, ctx.patient, ctx.encounter, ctx.approver)


def raise_requests_for_note(db, event, patient, encounter, approver: str) -> list[dict]:
    """Raise (or link to an open) investigation request for each study the note asks for.

    Idempotent: an open request for the same study in this encounter is reused, never duplicated.
    """
    payload = dict(event.payload or {})
    if payload.get("format") != "progress_v2" or payload.get("role", "doctor") != "doctor":
        return []
    from ..investigation_mentions import find_orders
    from ..timeline import add_audit, new_id

    sentences = [str((n or {}).get("text") if isinstance(n, dict) else n or "") for n in payload.get("notes") or []]
    orders = find_orders(sentences)
    if not orders:
        return []
    open_studies = {
        (r.study or "").lower(): r
        for r in db.scalars(select(InvestigationRequest).where(
            InvestigationRequest.encounter_id == encounter.id, InvestigationRequest.status.in_(OPEN_REQUEST)))
    }
    marked = []
    for order in orders:
        existing = open_studies.get(order["study"].lower())
        if existing is None:
            existing = InvestigationRequest(
                id=new_id("inv"), patient_id=patient.id, encounter_id=encounter.id,
                request_type=order["request_type"], study=order["study"], indication=order["sentence"],
                diagnosis="", allergies_to_verify=[], priority=order["priority"],
                instructions="Raised from the doctor's progress note", status="requested",
                approved_by=approver, created_at=utcnow(), source_event_id=event.id,
            )
            db.add(existing)
            db.flush()
            open_studies[order["study"].lower()] = existing
            add_audit(db, "investigation_auto_requested", "investigation_request", existing.id, patient.id,
                      actor_name=approver, after={"study": existing.study, "from_event": event.id})
        marked.append({**order, "request_id": existing.id, "status": existing.status})
    payload["orders"] = marked
    event.payload = payload
    return marked
