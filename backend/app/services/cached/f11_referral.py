"""F11 referral draft built only from the record: demographics, quoted assessment lines, abnormal results."""

from __future__ import annotations

from typing import Any

from .common import _claim, _events, _patient

PLACEHOLDER_QUESTION = "Question to be written by the referring clinician"

RENAL_LABS = {"egfr", "creatinine", "urea", "bun"}
ABNORMAL_FLAGS = {"high", "low"}
NOTE_TYPES = ("consult_note", "admission_note", "round_note", "progress_note")


def abnormal_results(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [lab for lab in context.get("latest_labs", []) if str(lab.get("flag", "")).lower() in ABNORMAL_FLAGS]


def _lab_text(lab: dict[str, Any]) -> str:
    return f"{lab['name']} {lab.get('value')} {lab.get('unit', '')}".strip()


def infer_specialty(context: dict[str, Any]) -> str | None:
    """Abnormal renal results give Nephrology; nothing else is inferred."""
    for lab in abnormal_results(context):
        if str(lab.get("name", "")).lower() in RENAL_LABS:
            return "Nephrology"
    return None


def assessment_claims(context: dict[str, Any]) -> list[tuple[str, str]]:
    """(quoted assessment line, note event id) from the latest approved note of each kind."""
    found: list[tuple[str, str]] = []
    for note_type in NOTE_TYPES:
        note = next((e for e in _events(context, note_type) if e.get("status") == "approved"), None)
        if not note:
            continue
        items = (note.get("payload") or {}).get("assessment") or []
        if isinstance(items, (str, dict)):
            items = [items]
        for item in items:
            text = item.get("text") if isinstance(item, dict) else item
            text = str(text or "").strip()
            if text and (text, note["id"]) not in found:
                found.append((text, note["id"]))
    return found


def _history(context: dict[str, Any]) -> dict[str, Any]:
    patient = _patient(context)
    sex = str(patient.get("sex") or "").strip().lower()
    age = f"{patient['age']}-year-old" if patient.get("age") is not None else ""
    who = " ".join(part for part in (age, sex) if part)
    parts = [(who or "Patient") + "."]
    problems = patient.get("problems") or []
    parts.append("Problems on record: " + ("; ".join(problems) if problems else "none recorded") + ".")
    evidence: list[str] = []
    assessments = assessment_claims(context)
    if assessments:
        parts.append("Assessment in approved notes: " + " ".join(f'"{text}"' for text, _ in assessments))
        evidence.extend(event_id for _, event_id in assessments)
    abnormal = abnormal_results(context)
    if abnormal:
        parts.append("Abnormal results: " + "; ".join(f"{_lab_text(lab)} ({lab['flag']})" for lab in abnormal) + ".")
        evidence.extend(lab["event_id"] for lab in abnormal)
    return _claim(" ".join(parts), list(dict.fromkeys(evidence)))


def _question(text: str | None) -> dict[str, Any]:
    text = (text or "").strip()
    if text:
        return _claim(text, [], confidence=1.0)
    return _claim(PLACEHOLDER_QUESTION, [], confidence=0.0)


def apply_request(content: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Re-impose what the clinician asked for (specialty, urgency, question) on any draft content."""
    if request.get("specialty"):
        content["specialty"] = request["specialty"]
        if content.get("specialist"):
            content["specialist"] = f"{request['specialty']} service"
    if request.get("urgency"):
        content["urgency"] = request["urgency"]
    content["question"] = _question(request.get("question"))
    return content


def f11_referral(context: dict[str, Any]) -> dict[str, Any]:
    request = context.get("referral_request") or {}
    specialty = request.get("specialty") or infer_specialty(context)
    if not specialty:
        raise ValueError("Choose a specialty")
    results = [_claim(_lab_text(lab), [lab["event_id"]]) for lab in abnormal_results(context)]
    history = _history(context)
    return {
        "specialty": specialty,
        "specialist": f"{specialty} service",
        "question": _question(request.get("question")),
        "history": history,
        "urgency": request.get("urgency") or "routine",
        "relevant_results": results,
        "source_event_ids": history["source_event_ids"],
    }


GENERATORS = {"F11": f11_referral}
