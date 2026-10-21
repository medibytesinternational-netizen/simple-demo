"""Approved investigation forms (F10) and referrals (F11) are queued for the hospital system.

Queuing happens in the approval transaction and never calls the network: approving must not
depend on the hospital system being up. The delivery job sends it and reports honestly.
"""

from __future__ import annotations

from typing import Any

from ...integrations import outbox
from . import ApprovalContext, after_event


@after_event("F10")
def queue_investigation(ctx: ApprovalContext, event: Any) -> None:
    resource = outbox.investigation_service_request(event.payload or {}, ctx.patient, ctx.approver, event.id)
    outbox.queue_message(ctx.db, resource, ctx.patient.id, event.id)


@after_event("F11")
def queue_referral(ctx: ApprovalContext, event: Any) -> None:
    resource = outbox.referral_service_request(event.payload or {}, ctx.patient, ctx.approver, event.id)
    outbox.queue_message(ctx.db, resource, ctx.patient.id, event.id)
