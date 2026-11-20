"""F1: the OPD note names the doctor who signs it as "History and physical recorded by"."""

from __future__ import annotations

from typing import Any

from ..opd import opd_header
from . import ApprovalContext, payload_builder


@payload_builder("F1")
def stamp_header(ctx: ApprovalContext, event_payload: dict[str, Any]) -> None:
    header = opd_header(ctx.patient, ctx.encounter, ctx.approver)
    event_payload["header"] = header
    # The stored document is rendered from the draft content; keep both the same.
    ctx.payload["header"] = header
