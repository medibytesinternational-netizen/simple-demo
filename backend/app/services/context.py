from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import Encounter, Patient, TimelineEvent
from .timeline import add_event, event_to_dict, list_events


def segments_from_transcript(text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) <= 1:
        lines = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    segments = []
    for index, line in enumerate(lines, start=1):
        speaker = "Clinician"
        spoken = line
        if ":" in line[:30]:
            candidate, rest = line.split(":", 1)
            if candidate.strip().lower() in {
                "doctor",
                "clinician",
                "dr",
                "dr.",
                "nurse",
                "patient",
                "ravi",
                "meera",
            }:
                speaker = candidate.strip().title()
                spoken = rest.strip()
        segments.append(
            {
                "segment_id": f"seg_{index}",
                "index": index,
                "speaker": speaker,
                "start_seconds": (index - 1) * 6,
                "text": spoken,
            }
        )
    return segments


def create_transcript_event(
    db: Session,
    patient: Patient,
    encounter: Encounter,
    feature: str,
    text: str,
    title: str,
) -> TimelineEvent:
    return add_event(
        db,
        patient_id=patient.id,
        encounter_id=encounter.id,
        type="transcript",
        subtype=feature,
        title=title,
        body_text=text,
        payload={"segments": segments_from_transcript(text), "feature": feature},
        source="input",
        author_type="human",
        author_name="Demo input",
        status="approved",
        approved_by="Demo input",
    )


_NOTE_TYPES = {"consult_note", "admission_note", "round_note", "progress_note"}
_CHANGE_TYPES = {
    "lab_result",
    "vitals",
    "device_reading",
    "med_order",
    "medication_administration",
    "nursing_chart",
    "referral_consult",
}


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except ValueError:
        return None


def _progress_context(events: list[TimelineEvent], state: dict[str, Any]) -> dict[str, Any]:
    """What F4 needs: the latest approved note and everything that changed after it."""
    live = [event for event in events if event.status == "approved"]
    notes = [event for event in live if event.type in _NOTE_TYPES]
    previous = max(notes, key=lambda event: event.occurred_at) if notes else None
    since = previous.occurred_at if previous else None

    changed = []
    for event in sorted(live, key=lambda e: e.occurred_at):
        if event.type not in _CHANGE_TYPES:
            continue
        if since is not None and event.occurred_at <= since:
            continue
        payload = event.payload or {}
        if event.type == "med_order" and payload.get("kind", "inpatient") == "home":
            continue
        changed.append(
            {
                "event_id": event.id,
                "type": event.type,
                "title": event.title,
                "occurred_at": event.occurred_at.isoformat(),
                "payload": payload,
            }
        )
    new_alerts = []
    for alert in state.get("alerts", []):
        created = _parse_time(alert.get("created_at"))
        if since is not None and created is not None and created <= since:
            continue
        new_alerts.append(
            {
                "alert_id": alert["id"],
                "rule_id": alert.get("rule_id"),
                "severity": alert.get("severity"),
                "status": alert.get("status"),
                "title": alert.get("title"),
                "evidence_event_ids": alert.get("evidence_event_ids", []),
                "created_at": alert.get("created_at"),
            }
        )
    return {
        "previous_note": {
            "event_id": previous.id,
            "type": previous.type,
            "title": previous.title,
            "occurred_at": previous.occurred_at.isoformat(),
        }
        if previous
        else None,
        "since_last": {"events": changed, "alerts": new_alerts},
    }


def _allergy_entry(allergy: Any, allergy_records: list[Any]) -> dict[str, Any]:
    """One patient allergy with the allergy record event that documents it.

    The patient row holds strings such as "Penicillin — rash"; the record event holds the
    substance alone. Match the whole string first, then the substance part, ignoring case.
    """
    text = str(allergy).strip().lower()
    base = text.split(" — ")[0].strip()

    def substance(event: Any) -> str:
        return str((event.payload or {}).get("substance", "")).strip().lower()

    match = next((e for e in allergy_records if substance(e) == text), None)
    if match is None and base:
        match = next((e for e in allergy_records if substance(e) == base), None)
    return {
        "substance": allergy,
        "event_id": match.id if match else "",
        "reaction": (match.payload or {}).get("reaction", "") if match else "",
    }


def build_context(
    db: Session,
    patient: Patient,
    encounter: Encounter,
    state: dict[str, Any],
    feature: str,
    transcript_event: TimelineEvent | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events = list_events(db, patient.id, encounter.id, approved_only=True, limit=1000)
    # Keep prompts compact while always retaining the important event types.
    priority_types = {
        "consult_note",
        "admission_note",
        "round_note",
        "progress_note",
        "nursing_summary",
        "nursing_chart",
        "icu_flow_sheet",
        "investigation_review",
        "referral",
        "investigation_request",
        "procedure",
        "vitals",
        "device_reading",
        "document_review",
        "discharge_summary",
        "billing",
        "allergy_record",
        "plan_action",
        "medication_administration",
    }
    selected = [event for event in events if event.type in priority_types or event.type in {"lab_result", "med_order"}]
    selected = selected[:120]
    allergy_records = [event for event in events if event.type == "allergy_record"]
    context: dict[str, Any] = {
        "patient": {
            **state["patient"],
            "allergies": [_allergy_entry(allergy, allergy_records) for allergy in state["patient"]["allergies"]],
        },
        "encounter": state["encounter"],
        "evidence_events": [event_to_dict(event) for event in selected],
        "home_medications": state["home_meds"],
        "active_medications": state["active_meds"],
        "latest_labs": state["latest_labs"],
        "unreviewed_labs": state["unreviewed_labs"],
        "vitals": state["vitals"],
        "icu_entries": state.get("icu_entries", []),
        "icu_shift_window": state.get("icu_shift_window", {}),
        "tasks": state["tasks"],
        "alerts": state["alerts"],
        "documents": state["documents"],
        "feature": feature,
    }
    if feature == "F4":
        context.update(_progress_context(events, state))
    if transcript_event:
        context["transcript"] = {
            "event_id": transcript_event.id,
            "segments": (transcript_event.payload or {}).get("segments", []),
        }
    if extra:
        context.update(extra)
    return context


def context_hash(context: dict[str, Any]) -> str:
    payload = json.dumps(context, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def allowed_evidence_ids(context: dict[str, Any]) -> set[str]:
    allowed: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"event_id", "source_event_id", "committed_event_id"} and isinstance(item, str):
                    if item.startswith("evt_"):
                        allowed.add(item)
                if key == "source_event_ids" and isinstance(item, list):
                    allowed.update(str(entry) for entry in item if str(entry).startswith("evt_"))
                if key == "source_segment_ids" and isinstance(item, list):
                    allowed.update(str(entry) for entry in item if str(entry).startswith("seg_"))
                if key == "evidence_event_ids" and isinstance(item, list):
                    allowed.update(str(entry) for entry in item if str(entry).startswith("evt_"))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            allowed.update(re.findall(r"evt_[a-zA-Z0-9]+", value))
            allowed.update(re.findall(r"seg_[a-zA-Z0-9]+", value))

    walk(context)
    if context.get("transcript"):
        allowed.add(context["transcript"]["event_id"])
        for segment in context["transcript"].get("segments", []):
            allowed.add(segment["segment_id"])
    return allowed


def context_digest(feature: str, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "feature": feature,
        "event_count": len(context.get("evidence_events", [])),
        "segment_count": len((context.get("transcript") or {}).get("segments", [])),
        "hash": context_hash(context),
    }
