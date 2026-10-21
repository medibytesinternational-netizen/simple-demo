"""Draft a note from a transcript by quoting it, never by writing new text.

Each sentence the speakers said is classified with plain keyword rules (complaint, history,
examination, assessment, plan, follow-up, medicines). The draft quotes the sentence exactly and
cites the segment it came from. A section with no matching sentence stays empty, which the
drafting code reports under ``not_documented``. This is what the demo uses without an AI key,
and as the fallback when a live model call fails.

Questions are never findings, so a sentence ending in "?" is history-taking, not documentation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")

_PATIENT_SPEAKERS = {"patient", "ravi"}
_NURSE_SPEAKERS = {"nurse", "nursing"}

_SYMPTOM = re.compile(
    r"\b(pain|ache|cough|wheez\w*|fever|chills|swelling|swollen|redness|breathless\w*|short of breath|nausea|vomit\w*|"
    r"dizz\w*|headache|rash|itch\w*|bleeding|weakness|fatigue|tired|palpitation\w*|diarrh\w*|constipation)\b",
    re.I,
)
_DURATION = re.compile(r"\b(for|since|over|past|last)\s+(\w+\s+){0,3}(hours?|days?|weeks?|months?|years?|night|tuesday|monday|wednesday|thursday|friday|saturday|sunday)\b", re.I)

_EXAM = re.compile(
    r"\b(on examination|examination|exam|auscultat\w*|palpat\w*|tender\w*|erythema\w*|temperature|pulse|blood pressure|"
    r"bp|spo2|saturations?|heart rate|respiratory rate|peak flow|wheeze|crepitation\w*|murmur|oedema|edema|ulcer|"
    r"your (chest|abdomen|leg|heart|lungs|throat|wound))\b|\b\d{2,3}/\d{2,3}\b",
    re.I,
)
_ASSESSMENT = re.compile(
    r"\b(looks like|likely|suspect\w*|diagnos\w*|impression|consistent with|probably|assessment|this is|appears to be|differential|i think)\b",
    re.I,
)
_PLAN = re.compile(
    r"\b(start|stop|continue|hold|withhold|admit|check|repeat|order|prescrib\w*|increase|decrease|reduce|refer|"
    r"book|arrange|advise|recommend|schedule|discharge|monitor|give|take|switch|change|add|avoid)\b"
    r"|\breview\s+(in|tomorrow|again|the|your|on|with|renal|him|her|them|at)\b",
    re.I,
)
_FOLLOW_UP = re.compile(
    r"\b(review in|follow[- ]?up|come back|return in|next visit|see you|in (\w+\s+)?(days?|weeks?|months?))\b", re.I
)

_DOSE = (
    r"(?:\d+(?:\.\d+)?|one|two|three|four|five|half)\s*"
    r"(?:mg|mcg|micrograms?|milligrams?|g\b|ml|units?|iu|puffs?|tablets?|capsules?|drops?)"
)
_FORM = r"(?:\s+(?:inhaler|tablets?|capsules?|injection|syrup|cream|drops|patch))?"
_MEDICINE = re.compile(rf"\b([a-z][a-z\-]{{3,}})\b{_FORM}\s+({_DOSE})", re.I)
_FREQUENCY = re.compile(
    r"\b((once|twice|three times|four times)\s+(a\s+|per\s+)?(day|daily|night|week)|every\s+\d+\s+hours|"
    r"as needed|when needed|daily|nightly|od|bd|tds|qds|prn|nocte)\b",
    re.I,
)
_NOT_A_DRUG = {
    "start", "stop", "with", "take", "give", "then", "also", "dose", "about", "every", "twice", "once", "three",
    "four", "five", "half", "this", "that", "will", "your", "need", "some", "more", "less", "today", "daily",
    "increase", "decrease", "reduce", "hold", "continue", "check", "repeat", "order", "review", "and", "the", "for",
}


@dataclass(frozen=True)
class Sentence:
    segment_id: str
    speaker: str
    role: str  # patient, nurse or clinician
    text: str

    @property
    def is_question(self) -> bool:
        return self.text.rstrip().endswith("?")


@dataclass(frozen=True)
class MedicineMention:
    sentence: Sentence
    drug: str
    dose: str
    frequency: str | None


@dataclass
class Analysis:
    sentences: list[Sentence] = field(default_factory=list)
    complaint: Sentence | None = None
    history: list[Sentence] = field(default_factory=list)
    exam: list[Sentence] = field(default_factory=list)
    assessment: list[Sentence] = field(default_factory=list)
    plan: list[Sentence] = field(default_factory=list)
    follow_up: list[Sentence] = field(default_factory=list)
    medicines: list[MedicineMention] = field(default_factory=list)
    nurse_lines: list[Sentence] = field(default_factory=list)

    def missing(self) -> list[str]:
        """Section names with nothing documented, for ``not_documented``."""
        gaps = []
        if not self.complaint:
            gaps.append("Presenting complaint")
        if not self.history:
            gaps.append("History")
        if not self.exam:
            gaps.append("Examination")
        if not self.assessment:
            gaps.append("Assessment")
        if not self.plan:
            gaps.append("Plan")
        return gaps


def _role(speaker: str) -> str:
    name = (speaker or "").strip().lower()
    if name in _PATIENT_SPEAKERS:
        return "patient"
    if name in _NURSE_SPEAKERS:
        return "nurse"
    return "clinician"


def split_sentences(segments: list[dict[str, Any]]) -> list[Sentence]:
    out: list[Sentence] = []
    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        role = _role(str(segment.get("speaker", "")))
        for part in _SENTENCE_SPLIT.split(text):
            part = part.strip()
            if part:
                out.append(Sentence(str(segment["segment_id"]), str(segment.get("speaker", "")), role, part))
    return out


def medicines_in(sentence: Sentence) -> list[MedicineMention]:
    found: list[MedicineMention] = []
    for match in _MEDICINE.finditer(sentence.text):
        drug = match.group(1)
        if drug.lower() in _NOT_A_DRUG:
            continue
        after = sentence.text[match.end() :]
        frequency = _FREQUENCY.search(after)
        found.append(MedicineMention(sentence, drug, match.group(2), frequency.group(0) if frequency else None))
    return found


def analyse(segments: list[dict[str, Any]]) -> Analysis:
    result = Analysis(sentences=split_sentences(segments))
    for sentence in result.sentences:
        text = sentence.text
        if sentence.role == "patient":
            result.history.append(sentence)
            if result.complaint is None and (_SYMPTOM.search(text) or _DURATION.search(text)):
                result.complaint = sentence
            continue
        if sentence.role == "nurse":
            result.nurse_lines.append(sentence)
            continue
        if sentence.is_question:
            continue
        if _EXAM.search(text):
            result.exam.append(sentence)
        if _ASSESSMENT.search(text):
            result.assessment.append(sentence)
        if _PLAN.search(text):
            result.plan.append(sentence)
        if _FOLLOW_UP.search(text):
            result.follow_up.append(sentence)
        result.medicines.extend(medicines_in(sentence))
    if result.complaint is None and result.history:
        result.complaint = result.history[0]
    return result


def claim(sentence: Sentence, transcript_event_id: str = "", confidence: float = 0.6) -> dict[str, Any]:
    """A draft claim that quotes one sentence and cites the segment it came from."""
    return {
        "text": sentence.text,
        "source_event_ids": [transcript_event_id] if transcript_event_id else [],
        "source_segment_ids": [sentence.segment_id],
        "confidence": confidence,
    }


def joined_claim(sentences: list[Sentence], transcript_event_id: str = "", confidence: float = 0.6) -> dict[str, Any] | None:
    """One claim quoting several sentences in the order they were said; None when there are none."""
    if not sentences:
        return None
    return {
        "text": " ".join(sentence.text for sentence in sentences),
        "source_event_ids": [transcript_event_id] if transcript_event_id else [],
        "source_segment_ids": list(dict.fromkeys(sentence.segment_id for sentence in sentences)),
        "confidence": confidence,
    }
