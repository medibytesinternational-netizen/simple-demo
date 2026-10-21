"""Send approved orders to the hospital system, and say honestly what has and has not gone.

A message is ``sent`` only after the hospital system answered 2xx. With ``FHIR_BASE_URL`` unset the
message is ``not_configured`` and stays visible; nothing pretends to send. Failures back off from
30 seconds, doubling, to one hour (the stored ``next_attempt_at``), so a dropped link mid-shift
loses nothing: the local record keeps working and the queue drains when the link returns.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import background
from ..db import utcnow
from ..models import Referral, TimelineEvent
from ..models_ext.s17_integration import IntegrationSync, OutboundMessage
from ..services.timeline import add_audit, new_id

ACTOR = "Outbox delivery"
FIRST_DELAY_SECONDS = 30
MAX_DELAY_SECONDS = 3600
MAX_ATTEMPTS = 10
TIMEOUT_SECONDS = 15

Transport = Callable[[str, bytes, dict[str, str], float], "tuple[int, str]"]

CATEGORY_CODES = {
    "laboratory": ("108252007", "Laboratory procedure"),
    "imaging": ("363679005", "Imaging"),
    "referral": ("3457005", "Patient referral"),
}


# ---------------------------------------------------------------- configuration (read at call time)
def base_url() -> str:
    """The configured FHIR base URL, or "" when unset or not http(s)."""
    raw = os.environ.get("FHIR_BASE_URL", "").strip()
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return ""
    return raw


def host_only(url: str) -> str:
    """hostname[:port] with no credentials, path or query."""
    parts = urlsplit(url)
    if not parts.hostname:
        return ""
    return f"{parts.hostname}:{parts.port}" if parts.port else parts.hostname


def _clean_target(url: str) -> tuple[str, dict[str, str]]:
    """The URL without userinfo, plus the headers that carry the credentials."""
    parts = urlsplit(url)
    headers: dict[str, str] = {}
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    if parts.username:
        raw = f"{parts.username}:{parts.password or ''}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    token = os.environ.get("FHIR_AUTH_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    clean = parts._replace(netloc=netloc).geturl().rstrip("/")
    return clean, headers


# ---------------------------------------------------------------- transport
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # a 3xx is never a success and never followed
        return None


def _opener(url: str) -> urllib.request.OpenerDirector:
    handlers: list[Any] = [_NoRedirect()]
    if (urlsplit(url).hostname or "") in {"127.0.0.1", "localhost", "::1"}:
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def urllib_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with _opener(url).open(request, timeout=timeout) as response:
            return response.status, response.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


# ---------------------------------------------------------------- building messages
def _stamp() -> str:
    return utcnow().isoformat() + "Z"


def _subject(patient) -> dict[str, Any]:
    return {
        "identifier": {
            "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "MR"}]},
            "value": patient.mrn,
        },
        "display": patient.name,
    }


def _category(kind: str) -> list[dict[str, Any]]:
    code, display = CATEGORY_CODES[kind]
    return [{"coding": [{"system": "http://snomed.info/sct", "code": code, "display": display}], "text": kind}]


def _claim_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("text", "")).strip()
    return str(value or "").strip()


def investigation_service_request(payload: dict[str, Any], patient, approver: str, event_id: str) -> dict[str, Any]:
    kind = "imaging" if str(payload.get("request_type", "laboratory")).lower() in {"imaging", "radiology"} else "laboratory"
    resource: dict[str, Any] = {
        "resourceType": "ServiceRequest",
        "identifier": [{"system": "urn:medibytes:event", "value": event_id}],
        "status": "active",
        "intent": "order",
        "category": _category(kind),
        "priority": payload.get("priority", "routine"),
        "code": {"text": str(payload.get("study", "Investigation"))},
        "subject": _subject(patient),
        "authoredOn": _stamp(),
        "requester": {"display": approver},
    }
    indication = _claim_text(payload.get("indication"))
    if indication:
        resource["reasonCode"] = [{"text": indication}]
    notes: list[dict[str, str]] = []
    allergies = []
    for item in payload.get("allergies_to_verify") or []:
        if isinstance(item, dict):
            substance = str(item.get("substance", "")).strip()
            reaction = str(item.get("reaction", "")).strip()
            if substance:
                allergies.append(f"{substance} ({reaction})" if reaction else substance)
        elif item:
            allergies.append(str(item))
    if allergies:
        notes.append({"text": "Allergies to verify: " + "; ".join(allergies)})
    if payload.get("instructions"):
        notes.append({"text": "Instructions: " + str(payload["instructions"])})
    if notes:
        resource["note"] = notes
    return resource


def referral_service_request(payload: dict[str, Any], patient, approver: str, event_id: str) -> dict[str, Any]:
    urgency = str(payload.get("urgency", "routine")).lower()
    priority = {"routine": "routine", "urgent": "urgent", "emergency": "stat"}.get(urgency, "routine")
    parts = []
    if _claim_text(payload.get("question")):
        parts.append("Question: " + _claim_text(payload["question"]))
    if _claim_text(payload.get("history")):
        parts.append("History: " + _claim_text(payload["history"]))
    resource: dict[str, Any] = {
        "resourceType": "ServiceRequest",
        "identifier": [{"system": "urn:medibytes:event", "value": event_id}],
        "status": "active",
        "intent": "order",
        "category": _category("referral"),
        "priority": priority,
        "code": {"text": str(payload.get("specialty", "Specialist service"))},
        "subject": _subject(patient),
        "authoredOn": _stamp(),
        "requester": {"display": approver},
    }
    if payload.get("specialist"):
        resource["performer"] = [{"display": str(payload["specialist"])}]
    if parts:
        resource["note"] = [{"text": "\n".join(parts)}]
    return resource


def queue_message(
    db: Session, resource: dict[str, Any], patient_id: str, source_event_id: str | None
) -> OutboundMessage:
    """Add a message to the outbox in the caller's transaction. Never touches the network."""
    configured = bool(base_url())
    message = OutboundMessage(
        id=new_id("out"),
        system=host_only(base_url()) or "hospital",
        resource_type=resource["resourceType"],
        payload=resource,
        status="queued" if configured else "not_configured",
        attempts=0,
        patient_id=patient_id,
        source_event_id=source_event_id,
        created_at=utcnow(),
        next_attempt_at=utcnow() if configured else None,
    )
    db.add(message)
    db.flush()
    return message


# ---------------------------------------------------------------- delivery
def backoff_seconds(attempts: int) -> int:
    return min(MAX_DELAY_SECONDS, FIRST_DELAY_SECONDS * 2 ** max(0, attempts - 1))


def _mark_referral_delivered(db: Session, message: OutboundMessage, now: datetime) -> None:
    """A referral is "sent" only once the hospital system accepted its message (2xx)."""
    event = db.get(TimelineEvent, message.source_event_id) if message.source_event_id else None
    if not event or event.type != "referral":
        return
    referral = db.get(Referral, (event.payload or {}).get("referral_id"))
    if not referral:
        return
    if referral.sent_at is None:
        referral.sent_at = now
    if referral.status == "queued":
        referral.status = "sent"


def deliver(db: Session, transport: Transport | None = None, now: datetime | None = None) -> dict[str, int]:
    """Try every message that is due. Returns counts of what happened."""
    send = transport or urllib_transport
    now = now or utcnow()
    result = {"sent": 0, "requeued": 0, "failed": 0, "not_configured": 0}
    url = base_url()
    if not url:
        for message in db.scalars(select(OutboundMessage).where(OutboundMessage.status == "queued")):
            message.status = "not_configured"
            message.last_error = "No hospital system address is configured."
            result["not_configured"] += 1
        db.commit()
        return result

    target, auth = _clean_target(url)
    for message in db.scalars(select(OutboundMessage).where(OutboundMessage.status == "not_configured")):
        message.status = "queued"
        message.last_error = None
        message.next_attempt_at = now
    db.flush()

    due = db.scalars(
        select(OutboundMessage)
        .where(OutboundMessage.status == "queued")
        .order_by(OutboundMessage.created_at)
    ).all()
    headers = {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json", **auth}
    for message in due:
        if message.next_attempt_at is not None and message.next_attempt_at > now:
            continue
        message.attempts = (message.attempts or 0) + 1
        error: str | None = None
        permanent = False
        try:
            status, _ = send(f"{target}/{message.resource_type}", json.dumps(message.payload).encode(), headers, TIMEOUT_SECONDS)
        except Exception as exc:  # a dropped link is an expected state, not a crash
            status, error = 0, f"network error: {type(exc).__name__}"
        if 200 <= status < 300:
            message.status = "sent"
            message.sent_at = now
            message.last_error = None
            message.next_attempt_at = None
            _mark_referral_delivered(db, message, now)
            result["sent"] += 1
            add_audit(db, "fhir_message_sent", "outbound_message", message.id, message.patient_id,
                      actor_type="system", actor_name=ACTOR,
                      after={"resource_type": message.resource_type, "attempts": message.attempts})
        else:
            if status:
                error = f"HTTP {status}"
                permanent = 400 <= status < 500 and status not in {408, 429}
            message.last_error = error
            if permanent or message.attempts >= MAX_ATTEMPTS:
                message.status = "failed"
                message.next_attempt_at = None
                result["failed"] += 1
                add_audit(db, "fhir_message_failed", "outbound_message", message.id, message.patient_id,
                          actor_type="system", actor_name=ACTOR,
                          after={"error": error, "attempts": message.attempts})
            else:
                message.next_attempt_at = now + timedelta(seconds=backoff_seconds(message.attempts))
                result["requeued"] += 1
        db.commit()
    db.commit()
    return result


def retry(db: Session) -> dict[str, int]:
    """Put failed messages (and held ones, once an address is set) back in the queue now."""
    now = utcnow()
    requeued = 0
    configured = bool(base_url())
    for message in db.scalars(
        select(OutboundMessage).where(OutboundMessage.status.in_(["failed", "not_configured"]))
    ):
        if message.status == "not_configured" and not configured:
            continue
        message.status = "queued"
        message.attempts = 0
        message.last_error = None
        message.next_attempt_at = now
        requeued += 1
    db.flush()
    return {"requeued": requeued}


# ---------------------------------------------------------------- status
def _clock(value: datetime | None) -> str:
    return value.strftime("%H:%M") if value else ""


def _messages(count: int, verb: str) -> str:
    return f"{count} message{'s' if count != 1 else ''} {verb}"


def status(db: Session) -> dict[str, Any]:
    url = base_url()
    counts = dict(db.execute(select(OutboundMessage.status, func.count()).group_by(OutboundMessage.status)).all())
    queued, failed, held = counts.get("queued", 0), counts.get("failed", 0), counts.get("not_configured", 0)
    last = db.scalars(select(IntegrationSync).order_by(IntegrationSync.started_at.desc())).first()
    last_at = (last.finished_at or last.started_at) if last else None

    sentences: list[str] = []
    if not url:
        sentences.append("No hospital system is connected.")
    if last is None:
        if url:
            sentences.append("Nothing received from the hospital system yet.")
    elif last.status == "failed":
        sentences.append(f"Last sync failed at {_clock(last_at)}.")
    else:
        sentences.append(f"Last synced {_clock(last_at)}.")
    if held:
        sentences.append(_messages(held, "held, not sent") + ".")
    if queued:
        sentences.append(_messages(queued, "waiting") + ".")
    if failed:
        sentences.append(_messages(failed, "failed to send") + ".")
    if url and not (held or queued or failed) and last is not None:
        sentences.append("No messages waiting.")
    return {
        "configured": bool(url),
        "host": host_only(url),
        "last_sync_at": last_at.isoformat() if last_at else None,
        "last_sync_status": last.status if last else None,
        "queued": queued,
        "failed": failed,
        "not_configured": held,
        "banner": " ".join(sentences),
    }


def _job(db: Session) -> dict[str, int]:
    return deliver(db)


background.register("outbox-delivery", _job, 60)
