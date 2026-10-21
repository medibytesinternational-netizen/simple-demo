from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from ..models import Encounter, Patient, TimelineEvent
from .timeline import add_event, event_to_dict, list_events, new_id


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
    allergy_events = {
        str((event.payload or {}).get("substance", "")).lower(): event.id
        for event in events
        if event.type == "allergy_record"
    }
    context: dict[str, Any] = {
        "patient": {
            **state["patient"],
            "allergies": [
                {
                    "substance": allergy,
                    "event_id": allergy_events.get(str(allergy).lower(), ""),
                    "reaction": next(
                        (
                            (event.payload or {}).get("reaction", "")
                            for event in events
                            if event.type == "allergy_record"
                            and str((event.payload or {}).get("substance", "")).lower() == str(allergy).lower()
                        ),
                        "",
                    ),
                }
                for allergy in state["patient"]["allergies"]
            ],
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
