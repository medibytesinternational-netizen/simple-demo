from __future__ import annotations

import json
import re
import time
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..db import utcnow
from ..models import LLMCall
from ..prompts import VERSIONS, load_prompt
from ..schemas import FEATURE_MODELS
from .cached import cached_draft
from .context import allowed_evidence_ids, context_hash
from .timeline import new_id

NUMBER_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(mg|g|mcg|ml|dL|mmol|mEq|%|bpm|°C|cm|kg)",
    re.IGNORECASE,
)


class DraftGenerationError(Exception):
    def __init__(self, message: str, llm_call_id: str | None = None):
        super().__init__(message)
        self.llm_call_id = llm_call_id


def _walk_claims(value: Any):
    if isinstance(value, dict):
        if "text" in value and isinstance(value.get("text"), str) and (
            "source_event_ids" in value or "source_segment_ids" in value
        ):
            yield value
        for item in value.values():
            yield from _walk_claims(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_claims(item)


def _walk_source_ids(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"source_event_ids", "source_segment_ids", "evidence_event_ids", "source_event_id"}:
                if isinstance(item, list):
                    for entry in item:
                        yield str(entry)
                elif item:
                    yield str(item)
            yield from _walk_source_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_source_ids(item)


def validate_evidence(content: dict[str, Any], context: dict[str, Any]) -> list[str]:
    allowed = allowed_evidence_ids(context)
    cited = set(_walk_source_ids(content))
    return sorted(item for item in cited if item and item not in allowed)


def validate_numbers(content: dict[str, Any], context: dict[str, Any]) -> list[str]:
    haystack = json.dumps(context, default=str)
    missing = []
    for claim in _walk_claims(content):
        for match in NUMBER_UNIT_RE.finditer(claim["text"]):
            number = match.group(1)
            if number not in haystack:
                missing.append(f"{number}{match.group(2)} in: {claim['text'][:90]}")
    return missing


def _live_call(feature: str, prompt: str, context: dict[str, Any], model_cls: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    schema_text = json.dumps(model_cls.model_json_schema(), default=str)
    messages = [
        {
            "role": "system",
            "content": (
                f"{prompt}\n\nReturn only a JSON object. It must validate against this JSON Schema:\n"
                f"{schema_text}\nNever include markdown fences or commentary."
            ),
        },
        {
            "role": "user",
            "content": "CONTEXT:\n" + json.dumps(context, default=str, indent=2),
        },
    ]
    started = time.perf_counter()
    completion = client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        temperature=0.1,
        response_format={"type": "json_object"},
        timeout=45,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    raw = completion.choices[0].message.content or "{}"
    parsed = json.loads(raw)
    usage = {
        "latency_ms": latency_ms,
        "input_tokens": getattr(completion.usage, "prompt_tokens", 0) if completion.usage else 0,
        "output_tokens": getattr(completion.usage, "completion_tokens", 0) if completion.usage else 0,
        "request_json": {"messages": messages},
    }
    return parsed, usage


def _repair_call(
    feature: str,
    prompt: str,
    context: dict[str, Any],
    model_cls: Any,
    errors: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    schema_text = json.dumps(model_cls.model_json_schema(), default=str)
    messages = [
        {
            "role": "system",
            "content": (
                f"{prompt}\n\nReturn only JSON matching this schema:\n{schema_text}\n"
                "A previous attempt failed these checks:\n- " + "\n- ".join(errors) +
                "\nRepair the output. Use only source ids that appear in the context. "
                "Use only numbers that appear in the context."
            ),
        },
        {
            "role": "user",
            "content": "CONTEXT:\n" + json.dumps(context, default=str, indent=2),
        },
    ]
    started = time.perf_counter()
    completion = client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        temperature=0.1,
        response_format={"type": "json_object"},
        timeout=45,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    parsed = json.loads(completion.choices[0].message.content or "{}")
    usage = {
        "latency_ms": latency_ms,
        "input_tokens": getattr(completion.usage, "prompt_tokens", 0) if completion.usage else 0,
        "output_tokens": getattr(completion.usage, "completion_tokens", 0) if completion.usage else 0,
        "request_json": {"messages": messages, "repair": True},
    }
    return parsed, usage


def _deterministic_medications(context: dict[str, Any]) -> list[dict[str, Any]]:
    open_alerts = [
        alert for alert in context.get("alerts", []) if alert.get("status") == "open"
    ]
    meds = []
    for med in context.get("active_medications", []):
        event_id = med.get("event_id", "")
        linked_alerts = [
            alert
            for alert in open_alerts
            if event_id in (alert.get("evidence_event_ids") or [])
        ]
        linked = max(
            linked_alerts,
            key=lambda alert: 1 if alert.get("severity") == "critical" else 0,
            default=None,
        )
        meds.append(
            {
                "drug": med.get("drug", ""),
                "dose": med.get("dose", ""),
                "route": med.get("route", ""),
                "frequency": med.get("frequency", ""),
                "status": "continue" if med.get("status", "active") == "active" else med.get("status", ""),
                "source_event_id": event_id,
                "safety_status": (
                    "contraindicated"
                    if linked and linked.get("severity") == "critical"
                    else "review"
                    if linked
                    else "ok"
                ),
                "safety_note": (
                    f"{linked.get('rule_id', '')}: {linked.get('title', '')}".strip(": ")
                    if linked
                    else ""
                ),
            }
        )
    return meds


def generate_draft(
    db: Session,
    feature: str,
    context: dict[str, Any],
) -> tuple[dict[str, Any], LLMCall]:
    model_cls = FEATURE_MODELS[feature]
    prompt = load_prompt(feature)
    mode = settings.effective_llm_mode
    content: dict[str, Any]
    usage: dict[str, Any] = {
        "latency_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "request_json": {},
    }
    errors: list[str] = []

    if mode == "live":
        try:
            raw, usage = _live_call(feature, prompt, context, model_cls)
            parsed = model_cls.model_validate(raw)
            content = parsed.model_dump(mode="json")
            evidence_errors = validate_evidence(content, context)
            number_errors = validate_numbers(content, context)
            if evidence_errors or number_errors:
                errors = [f"Unknown source id: {item}" for item in evidence_errors[:8]]
                errors += [f"Unsupported value: {item}" for item in number_errors[:8]]
                try:
                    raw, repair_usage = _repair_call(feature, prompt, context, model_cls, errors)
                    usage["latency_ms"] += repair_usage["latency_ms"]
                    usage["input_tokens"] += repair_usage["input_tokens"]
                    usage["output_tokens"] += repair_usage["output_tokens"]
                    parsed = model_cls.model_validate(raw)
                    content = parsed.model_dump(mode="json")
                except Exception:
                    mode = "cached"
                    content = cached_draft(feature, context)
        except Exception as exc:
            # Stage safety: never leave the demo with an empty screen.
            mode = "cached"
            errors.append(f"Live call failed: {type(exc).__name__}")
            content = cached_draft(feature, context)
    else:
        content = cached_draft(feature, context)

    if feature == "F9":
        content["medications"] = _deterministic_medications(context)
        # An unsourced follow-up, pending result or red flag is an invention, not
        # a summary. Keep only claims that point at an approved event or segment.
        for key in ("follow_up", "pending_results", "red_flags"):
            content[key] = [
                claim
                for claim in (content.get(key) or [])
                if claim.get("source_event_ids") or claim.get("source_segment_ids")
            ]
        sections = []
        for section in (content.get("sections") or []):
            paragraphs = [
                claim
                for claim in (section.get("paragraphs") or [])
                if claim.get("source_event_ids") or claim.get("source_segment_ids")
            ]
            if paragraphs:
                sections.append({**section, "paragraphs": paragraphs})
        content["sections"] = sections

    # F3 demo guarantee: if the model drops an explicit nurse action, derive a
    # draft nursing entry from the transcript instead of silently losing it.
    if feature == "F3" and not content.get("nursing_entries"):
        transcript = context.get("transcript") or {}
        transcript_id = transcript.get("event_id", "")
        nurse_segments = [
            segment
            for segment in transcript.get("segments", [])
            if str(segment.get("speaker", "")).lower() in {"nurse", "nursing"}
            and str(segment.get("text", "")).strip()
        ]
        content["nursing_entries"] = [
            {
                "text": str(segment["text"]).strip(),
                "source_event_ids": [transcript_id] if transcript_id else [],
                "source_segment_ids": [segment["segment_id"]],
                "confidence": 0.9,
            }
            for segment in nurse_segments
        ]

    # Final validation on whatever we are about to show.
    try:
        validated = model_cls.model_validate(content)
        content = validated.model_dump(mode="json")
    except Exception as exc:
        call = LLMCall(
            id=new_id("llm"),
            feature=feature,
            prompt_version=VERSIONS.get(feature, "v1"),
            model=settings.openai_model,
            mode=mode,
            status="schema_error",
            validation_errors=[str(exc)],
            response_json=content,
            created_at=utcnow(),
        )
        db.add(call)
        db.flush()
        raise DraftGenerationError(f"Draft failed schema validation: {exc}", call.id) from exc

    evidence_errors = validate_evidence(content, context)
    number_errors = validate_numbers(content, context)
    call = LLMCall(
        id=new_id("llm"),
        feature=feature,
        prompt_version=VERSIONS.get(feature, "v1"),
        prompt_hash=context_hash(context),
        model=settings.openai_model,
        temperature=0.1,
        context_hash=context_hash(context),
        request_json={
            "feature": feature,
            "context_event_count": len(context.get("evidence_events", [])),
        },
        response_json=content,
        status="ok" if not evidence_errors and not number_errors else "evidence_error",
        validation_errors=errors + evidence_errors + number_errors,
        latency_ms=int(usage.get("latency_ms", 0)),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        mode=mode,
        created_at=utcnow(),
    )
    db.add(call)
    db.flush()
    return content, call
