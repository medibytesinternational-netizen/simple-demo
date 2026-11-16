"""F1: store the signed OPD note as a document the timeline can open and print."""

from __future__ import annotations

from ...config import settings
from ...db import utcnow
from ..note_document import GENERATED_KIND, OPD_NOTE_TYPE, render_opd_note_html
from ..ocr import new_document
from ..timeline import add_audit
from . import ApprovalContext, after_event


@after_event("F1")
def store_note_document(ctx: ApprovalContext, event) -> None:
    signed_at = utcnow()
    html = render_opd_note_html(ctx.patient, ctx.encounter, ctx.payload, ctx.approver, signed_at)
    folder = settings.uploads_dir / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{event.id}.html"
    path.write_text(html, encoding="utf-8")

    document = new_document(
        ctx.db,
        patient_id=ctx.patient.id,
        encounter_id=ctx.encounter.id,
        filename=f"OPD note {ctx.patient.mrn} {signed_at:%Y-%m-%d %H%M}.html",
        path=str(path),
        mime="text/html",
        image_kind=GENERATED_KIND,
        doc_type=OPD_NOTE_TYPE,
    )
    document.ocr_status = "confirmed"
    document.confirmed_by = ctx.approver
    document.confirmed_at = signed_at
    event.document_id = document.id
    add_audit(
        ctx.db,
        "note_document_stored",
        "document",
        document.id,
        ctx.patient.id,
        actor_name=ctx.approver,
        after={"event_id": event.id, "doc_type": OPD_NOTE_TYPE},
    )
