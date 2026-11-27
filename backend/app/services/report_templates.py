"""Feature report templates applied to MediBytes' six-section note.

The templates and field rules are ported from the former local MediBytes templates. This layer
receives only the documented six-section API response and its needs_review items; the raw transcript
and extracted entities are not available here.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, create_model
from sqlalchemy.orm import Session

from ..config import settings
from ..db import utcnow
from ..models import LLMCall
from ..schemas import ADMISSION_HEARD_SECTIONS, OPD_HEARD_SECTIONS
from . import llm
from .medibytes_note import NOTE_FIELDS, NOTE_SECTIONS, note_segments
from .timeline import new_id

# key, rule, source fields, example sentence, example item, allow_many
TEMPLATES: dict[str, dict[str, Any]] = {
    "F1": {
        "name": "opd",
        "document": "OPD consultation note",
        "intro": "Structure a dictated outpatient consultation in the hospital OPD format.",
        "sections": [
            ("mode_of_admission", "How the patient came: walked in, brought by family, by ambulance, referred, or from emergency.", (), "", "", False),
            ("referring_physician", "The doctor or hospital that referred the patient, as named.", (), "", "", False),
            ("previous_admission", "Earlier hospital admissions: where, when and why.", (), "", "", False),
            ("previous_diagnosis", "Conditions diagnosed before this visit, one per item.", ("previous_diagnosis",), "He is a known diabetic for ten years.", "Known diabetic for ten years.", True),
            ("allergies", "Each allergy with its reaction; use only an allergy actually present in the note.", ("general_instructions",), "Penicillin gives her a rash.", "Drug: penicillin - rash", True),
            ("pain", "Pain site, duration, score, frequency and radiation, only when stated.", ("present_illness",), "Pain in the lower back for three weeks, seven out of ten.", "Lower back pain for three weeks, 7/10.", False),
            ("occupation", "The patient's work, as named.", (), "", "", False),
            ("source_of_history", "Who gave the history and whether reliability was stated.", (), "", "", False),
            ("chief_complaints", "Main complaints that brought the patient today, each with duration.", ("present_illness",), "Cough for two weeks and fever for three days.", "Cough for two weeks.", True),
            ("history_of_present_illness", "Current illness: onset, course, triggers, associated and denied symptoms.", ("present_illness",), "It started after a cold and gets worse at night.", "Started after a cold; worse at night.", False),
        ],
        "extra": (
            "Use only these headings. Examination, medicines, tests and plans are not part of OPD. "
            "Chief complaints are reasons for today's visit; the illness story goes in history_of_present_illness. "
            "previous_diagnosis means a diagnosis before this visit. Do not infer mode of admission, history source, occupation or previous admission."
        ),
    },
    "F2": {
        "name": "admission",
        "document": "admission note",
        "intro": "Structure a dictated hospital admission in the hospital admission format.",
        "sections": [
            ("admission_type", "Whether admission is Elective or Emergency, exactly as stated.", (), "", "", False),
            ("ward", "The ward or unit the patient is admitted to, as named.", (), "", "", False),
            ("speciality", "The speciality or department taking the patient, as stated.", ("general_instructions", "plan_of_management"), "She will be under general medicine.", "General medicine", False),
            ("provisional_diagnosis", "The working diagnosis for this admission, one per item.", ("plan_of_management",), "The provisional diagnosis is pneumonia.", "Pneumonia", True),
            ("proposed_treatment", "Treatment planned in hospital: medicines with dose, procedures and therapy.", ("plan_of_management",), "Start IV ceftriaxone 1 g twice daily.", "IV ceftriaxone 1 g twice daily", True),
            ("expected_outcome", "Expected outcome: Improved, Unchanged or Worsened, only if stated.", ("plan_of_management",), "I expect him to improve within a few days.", "Improve within a few days", False),
            ("possible_complications", "Complications the doctor says may happen.", ("plan_of_management",), "There is a risk of sepsis.", "Risk of sepsis", True),
            ("allergies", "Each allergy with reaction, or no known allergies only when stated.", ("general_instructions",), "He is allergic to penicillin; it gives a rash.", "Drug: penicillin - rash", True),
            ("cost_category", "Approximate cost or payment category, only when stated.", (), "", "", False),
            ("admission_labs", "Blood or lab tests ordered on admission.", ("plan_of_management",), "Send a CBC and renal function.", "CBC; renal function", True),
            ("imaging_studies", "Imaging studies ordered: x-ray, ultrasound, CT, MRI or echo.", ("plan_of_management",), "Get a chest x-ray.", "Chest x-ray", True),
            ("consultations_required", "Specialist opinions or referrals requested.", ("plan_of_management",), "We need a cardiology opinion.", "Cardiology opinion", True),
        ],
        "extra": (
            "Use only these headings. Admission type is exactly Elective or Emergency, and expected outcome is Improved, Unchanged or Worsened, only when the note states it. "
            "Tests go in admission_labs, scans in imaging_studies, opinions in consultations_required, and treatment in proposed_treatment. "
            "Do not guess ward, cost or outcome."
        ),
    },
    "F3": {
        "name": "progress",
        "document": "ward-round handover",
        "intro": "Structure a dictated ward-round note as a concise list of the observations, findings, changes, treatment and plan stated.",
        "sections": [
            ("notes", "Each observation, finding, change, treatment given or plan stated, in order.", NOTE_FIELDS, "Patient is afebrile since morning and tolerating oral feeds.", "Afebrile since morning; tolerating oral feeds.", True),
        ],
        "extra": "Keep each item short and in the order stated. Never add an examination finding, assessment, task or plan that the six-section note does not say.",
    },
    "F4": {
        "name": "progress",
        "document": "daily progress note",
        "intro": "Structure a dictated daily progress note (doctor's or nurse's).",
        "sections": [
            ("notes", "Each observation, finding, change, treatment given or plan stated, in order.", NOTE_FIELDS, "Patient is afebrile since morning and tolerating oral feeds.", "Afebrile since morning; tolerating oral feeds.", True),
        ],
        "extra": "Use only the notes heading. Keep each item short and in the order stated. Never add findings nobody said.",
    },
    "F11": {
        "name": "referral",
        "document": "hospital referral form, part one",
        "intro": "Structure a dictated hospital referral for the referring doctor.",
        "sections": [
            ("referral_type", "How fast it is needed: exactly Immediate, Urgent or Routine when stated.", ("general_instructions", "plan_of_management"), "Please see him urgently within four hours.", "Urgent", False),
            ("unit_chief", "The doctor or unit chief the referral is addressed to, by name.", (), "", "", False),
            ("department", "The department or speciality referred to, when named.", ("plan_of_management", "general_instructions"), "This is a referral to cardiology.", "Cardiology", False),
            ("salient_details", "Salient details and reason for referral: findings, results and the explicit request to the specialist.", NOTE_FIELDS, "New atrial fibrillation with a rate of 140; please advise on rate control.", "New atrial fibrillation with a rate of 140; rate-control advice requested.", True),
        ],
        "extra": "Use only these headings. Never guess the doctor's name, department or urgency. Leave a field empty when the note does not supply it.",
    },
    "F9": {
        "name": "discharge",
        "document": "discharge note",
        "intro": "Structure a dictated discharge note into the hospital's six discharge sections.",
        "sections": [
            ("present_illness", "Symptoms and duration, including denied symptoms only as stated.", ("present_illness",), "Burning chest discomfort after meals for one month.", "Burning chest discomfort after meals for one month.", True),
            ("examination_findings", "Vital readings and other examination findings.", ("examination_findings",), "Abdomen soft and non-tender.", "Abdomen soft and non-tender.", True),
            ("previous_diagnosis", "Past history and diagnoses.", ("previous_diagnosis",), "Previously diagnosed with GERD.", "Previously diagnosed with GERD.", True),
            ("plan_of_management", "Prescribed drugs with dose and frequency, follow-up, referrals and therapy.", ("plan_of_management",), "Increase omeprazole to 20 mg daily; review in four weeks.", "Increase omeprazole to 20 mg daily; review in four weeks.", True),
            ("diet_instructions", "Only diet, food or fluid advice actually stated.", ("diet_instructions",), "Avoid spicy food.", "Avoid spicy food.", True),
            ("general_instructions", "Allergy statements and other spoken advice.", ("general_instructions",), "Report any difficulty swallowing immediately.", "Report difficulty swallowing immediately.", True),
        ],
        "extra": "Use only these six sections. Do not add advice, medicines, facts or a follow-up that is not in the supplied note.",
    },
}

def _prompt(feature: str) -> str:
    spec = TEMPLATES[feature]
    rows = []
    for key, rule, sources, sentence, item, many in spec["sections"]:
        source_text = ", ".join(sources) if sources else "none; this field cannot be supplied by the six-section API note"
        example = f' Example for style only: input "{sentence}" -> item "{item}".' if sentence else ""
        rows.append(f"- {key} ({'many' if many else 'single'}): {rule} Allowed source fields: {source_text}.{example}")
    return (
        f"You are a clinical scribe. {spec['intro']}\n\n"
        "The only medical evidence is the supplied MediBytes six-section note. The needs_review list is a warning list, not evidence. "
        "Do not use outside facts, the patient record, or prior knowledge. Never invent or infer a fact. Anything not said stays empty and is shown to the clinician as not documented.\n"
        "For each output item, source_section must be one of the six input field names, source_sentence must be copied exactly from that field, and text must be copied exactly from source_sentence. "
        "If the note does not explicitly supply a field, return an empty items list for it. Do not use examples as patient facts.\\n\\n"
        f"Feature fields:\n{chr(10).join(rows)}\n\n{spec['extra']}\n"
        'Return only {"sections": {"field": {"items": [{"text": "...", "source_sentence": "...", "source_section": "...", "confidence": 0.9}]}}}. Include every listed field. Use an empty items list for unavailable fields.'
    )


def _output_model(feature: str):
    class Item(BaseModel):
        text: str
        source_sentence: str
        source_section: str
        confidence: float = 0.9

    class Section(BaseModel):
        items: list[Item] = Field(default_factory=list)

    section_model = create_model(
        f"{feature}TemplateSections",
        **{key: (Section, ...) for key, *_ in TEMPLATES[feature]["sections"]},
    )
    return create_model(f"{feature}TemplateOutput", sections=(section_model, ...))


def _validated_sections(feature: str, note: dict[str, str], raw: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    output_model = _output_model(feature).model_validate(raw).model_dump(mode="python")
    allowed_by_key = {key: set(sources) for key, _rule, sources, *_ in TEMPLATES[feature]["sections"]}
    result: dict[str, list[dict[str, Any]]] = {}
    for key, _rule, _sources, _sentence, _item, many in TEMPLATES[feature]["sections"]:
        accepted = []
        for item in output_model["sections"].get(key, {}).get("items", []):
            source_section = item["source_section"]
            source_sentence = str(item["source_sentence"]).strip()
            text = str(item["text"]).strip()
            source = note.get(source_section, "")
            if (
                source_section not in NOTE_FIELDS
                or source_section not in allowed_by_key[key]
                or not source_sentence
                or source_sentence not in source
                or not text
                or text not in source_sentence
            ):
                continue
            accepted.append({**item, "source_sentence": source_sentence, "text": text})
            if not many:
                break
        result[key] = accepted
    return result


def _cached_sections(feature: str, note: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """Conservative cached template: retain source phrases and leave uncertain fields empty."""
    result: dict[str, list[dict[str, Any]]] = {}

    def sentences(value: str) -> list[str]:
        return [part.strip(" \t\r\n•-*") for part in re.split(r"(?<=[.!?])\s+|\n+", value) if part.strip(" \t\r\n•-*")]

    admission_filters = {
        "speciality": r"\b(?:under|service|speciality|specialty|department)\b",
        "provisional_diagnosis": r"\b(?:diagnos(?:is|ed)|provisional|working diagnosis)\b",
        "proposed_treatment": r"\b(?:start|give|administer|treat|begin|continue|increase|decrease|stop|prescribe|therapy|procedure|surgery|\d+\s*mg|intravenous|\bIV\b)\b",
        "expected_outcome": r"\b(?:expect|improv\w*|unchanged|worsen\w*|prognos\w*|recover\w*)\b",
        "possible_complications": r"\b(?:risk|complication|may develop|could develop)\b",
        "allergies": r"\b(?:allerg\w*|no known (?:drug )?allergies)\b",
        "admission_labs": r"\b(?:CBC|complete blood count|renal function|electrolyte|laboratory|lab(?:s)?|urine|culture|hemoglobin|haemoglobin)\b",
        "imaging_studies": r"\b(?:x[ -]?ray|CT|MRI|ultrasound|USG|echocardiogram|echo|scan)\b",
        "consultations_required": r"\b(?:consult\w*|specialist|opinion|refer\w*)\b",
    }
    specialty_names = re.compile(
        r"\b(cardiology|neurology|nephrology|oncology|orthop(?:aedics|edics)|gastroenterology|"
        r"pulmonology|respiratory medicine|general medicine|general surgery|urology|dermatology|"
        r"endocrinology|psychiatry|ophthalmology|ENT)\b",
        re.IGNORECASE,
    )

    for key, _rule, sources, _sentence, _item, many in TEMPLATES[feature]["sections"]:
        found = []
        if feature == "F11" and key == "unit_chief":
            result[key] = found
            continue
        for source_section in sources:
            value = str(note.get(source_section) or "").strip()
            if not value:
                continue
            candidates = sentences(value)
            filtered = False
            if feature == "F2" and key in admission_filters:
                candidates = [sentence for sentence in candidates if re.search(admission_filters[key], sentence, re.IGNORECASE)]
                filtered = True
            if feature == "F1" and key == "allergies":
                candidates = [sentence for sentence in candidates if re.search(r"\b(?:allerg\w*|no known (?:drug )?allergies)\b", sentence, re.IGNORECASE)]
                filtered = True
            if feature == "F1" and key == "pain":
                candidates = [sentence for sentence in candidates if re.search(r"\b(?:pain|ache|sore|tender|radiat\w*|\d+\s*/\s*10)\b", sentence, re.IGNORECASE)]
                filtered = True
            if feature == "F11" and key == "referral_type":
                candidates = [sentence for sentence in candidates if re.search(r"\b(?:immediate|urgent|routine|emergency|stat)\b", sentence, re.IGNORECASE)]
                for sentence in candidates:
                    match = re.search(r"\b(?:immediate|urgent|routine|emergency|stat)\b", sentence, re.IGNORECASE)
                    if match:
                        found.append({"text": match.group(0), "source_sentence": sentence, "source_section": source_section, "confidence": 0.9})
                        break
                if found:
                    break
                continue
            if not many and not filtered:
                candidates = [value]
            if feature == "F11" and key == "department":
                for sentence in candidates:
                    match = specialty_names.search(sentence)
                    if match:
                        found.append({"text": match.group(0), "source_sentence": sentence, "source_section": source_section, "confidence": 0.9})
                        break
                if found:
                    break
                continue
            # The referral salience field is a list; other sections are represented by their
            # source sentence rather than copied into every related form field.
            for sentence in candidates:
                if not any(item["source_sentence"] == sentence and item["source_section"] == source_section for item in found):
                    found.append({"text": sentence, "source_sentence": sentence, "source_section": source_section, "confidence": 0.9})
                if not many:
                    break
            if found and not many:
                break
        result[key] = found
    return result


def _claims(items: list[dict[str, Any]], event_id: str, segment_ids: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "text": item["text"],
            "source_event_ids": [event_id] if event_id else [],
            "source_segment_ids": [segment_ids[item["source_section"]]] if item["source_section"] in segment_ids else [],
            "confidence": min(1.0, max(0.0, float(item.get("confidence", 0.9)))),
        }
        for item in items
    ]


def _joined(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    return {
        "text": "; ".join(item["text"] for item in items),
        "source_event_ids": list(dict.fromkeys(source for item in items for source in item["source_event_ids"])),
        "source_segment_ids": list(dict.fromkeys(source for item in items for source in item["source_segment_ids"])),
        "confidence": min(item["confidence"] for item in items),
    }


def _review(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {"section": item["section"], "text": item["text"]}
        for item in value
        if isinstance(item, dict) and isinstance(item.get("section"), str) and isinstance(item.get("text"), str)
    ]


def _content(feature: str, sections: dict[str, list[dict[str, Any]]], note: dict[str, str], event_id: str, needs_review: Any) -> dict[str, Any]:
    segment_ids = {segment["section"]: segment["segment_id"] for segment in note_segments(note)}
    grouped = {key: _claims(items, event_id, segment_ids) for key, items in sections.items()}
    review = _review(needs_review)
    single_claims = {key: _joined(grouped.get(key, [])) for key, _rule, _sources, _sentence, _item, many in TEMPLATES[feature]["sections"] if not many}

    if feature == "F1":
        from .opd import OPD_FORMAT, heard_not_documented
        content = {"format": OPD_FORMAT, **grouped, **single_claims, "needs_review": review}
        content["not_documented"] = heard_not_documented(content)
        return content
    if feature == "F2":
        from .admission import ADMIT_FORMAT, not_documented
        content = {"format": ADMIT_FORMAT, **grouped, **single_claims, "needs_review": review}
        content["not_documented"] = not_documented(content)
        return content
    if feature == "F3":
        note_claims = grouped.get("notes", [])
        return {
            "note_claims": note_claims,
            "nursing_entries": [],
            "proposed_tasks": [],
            "not_documented": [] if note_claims else ["Round note"],
            "needs_review": review,
        }
    if feature == "F4":
        from .progress import PROGRESS_FORMAT
        notes = grouped.get("notes", [])
        return {
            "format": PROGRESS_FORMAT,
            "notes": notes,
            "not_documented": [] if notes else ["Notes"],
            "needs_review": review,
        }
    if feature == "F11":
        from .referral_form import REFERRAL_FORMAT, missing, referral_type
        type_claim = (grouped.get("referral_type") or [None])[0]
        content = {
            "format": REFERRAL_FORMAT,
            "referral_type": referral_type(type_claim["text"]) if type_claim else None,
            "unit_chief": single_claims.get("unit_chief"),
            "department": single_claims.get("department"),
            "salient_details": grouped.get("salient_details", []),
            "needs_review": review,
        }
        content["not_documented"] = missing(content)
        return content
    headings = {key: label for key, label in NOTE_SECTIONS}
    paragraphs = []
    for field, _label in NOTE_SECTIONS:
        claims = grouped.get(field, [])
        paragraphs.append({"heading": headings[field], "paragraphs": claims})
    return {
        "sections": paragraphs,
        "not_documented": [headings[field] for field, _label in NOTE_SECTIONS if not grouped.get(field)],
        "needs_review": review,
    }


def generate_report_template(
    db: Session,
    feature: str,
    note: dict[str, str],
    needs_review: Any,
    event_id: str,
) -> tuple[dict[str, Any], LLMCall]:
    """Run the feature template through the app's live/cached LLM layer and return evidence-linked content."""
    if feature not in TEMPLATES:
        raise ValueError(f"No voice report template for {feature}")
    normalized = {key: str(note.get(key) or "") for key in NOTE_FIELDS}
    review = _review(needs_review)
    context = {"note_content": normalized, "needs_review": review}
    prompt = _prompt(feature)
    mode = settings.effective_llm_mode
    errors: list[str] = []
    usage = {"latency_ms": 0, "input_tokens": 0, "output_tokens": 0}
    sections: dict[str, list[dict[str, Any]]]

    if mode == "live":
        try:
            raw, usage = llm._live_call(feature, prompt, context, _output_model(feature))
            sections = _validated_sections(feature, normalized, raw)
            # Empty sections are expected; malformed or unsupported claims are already dropped.
        except Exception as exc:
            errors.append(f"Template call failed: {type(exc).__name__}")
            mode = "cached"
            sections = _cached_sections(feature, normalized)
    else:
        sections = _cached_sections(feature, normalized)

    content = _content(feature, sections, normalized, event_id, review)
    context_hash = llm.context_hash(context)
    call = LLMCall(
        id=new_id("llm"),
        feature=feature,
        prompt_version=f"report-{TEMPLATES[feature]['name']}-v1",
        prompt_hash=context_hash,
        model=settings.active_model if mode == "live" else "cached",
        temperature=0.1,
        context_hash=context_hash,
        request_json={"feature": feature, "template": TEMPLATES[feature]["name"], "prompt": prompt, "context": context},
        response_json=content,
        status="ok",
        validation_errors=errors,
        latency_ms=int(usage.get("latency_ms", 0)),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        mode=mode,
        created_at=utcnow(),
    )
    db.add(call)
    db.flush()
    return content, call
