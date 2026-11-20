"""Find scans and lab reports a doctor asks for in a progress note.

Rule-based on purpose: deterministic, testable, and it works in cached/demo mode.
A study named in a doctor's note is treated as an order, because plans are often dictated
as a bare list ("One, CT abdomen and pelvis to rule out a collection"). It is skipped only
when the sentence cancels the study or reports its result.
"""
from __future__ import annotations

import re
from typing import Any

# (pattern, label, category, request_type). Specific before generic; overlapping matches are skipped.
STUDIES: list[tuple[str, str, str, str]] = [
    (r"\b(?:chest\s+x-?ray|cxr)\b", "Chest X-ray", "xray", "imaging"),
    (r"\bct\b", "CT", "ct", "imaging"),
    (r"\bmri\b", "MRI", "mri", "imaging"),
    (r"\bx-?ray\b", "X-ray", "xray", "imaging"),
    (r"\b(?:usg|ultrasound|sonography)\b", "Ultrasound", "ultrasound", "imaging"),
    (r"\bdoppler\b", "Doppler", "ultrasound", "imaging"),
    (r"\b(?:2d echo|echo|echocardiogra(?:m|phy))\b", "Echocardiogram", "ultrasound", "imaging"),
    (r"\b(?:ecg|ekg)\b", "ECG", "ecg", "imaging"),
    (r"\b(?:cbc|complete blood count|full blood count)\b", "Complete blood count", "lab", "laboratory"),
    (r"\b(?:lft|liver function(?:\s+tests?)?)\b", "Liver function tests", "lab", "laboratory"),
    (r"\b(?:rft|kft|renal function(?:\s+tests?)?|kidney function(?:\s+tests?)?)\b", "Renal function tests", "lab", "laboratory"),
    (r"\b(?:serum electrolytes|electrolytes|potassium|sodium)\b", "Serum electrolytes", "lab", "laboratory"),
    (r"\bhba1c\b", "HbA1c", "lab", "laboratory"),
    (r"\b(?:blood|urine|wound|pus|sputum)\s+culture\b", "Culture", "lab", "laboratory"),
    (r"\b(?:crp|esr|procalcitonin)\b", "Inflammatory markers", "lab", "laboratory"),
    (r"\b(?:blood tests?|lab tests?|bloods)\b", "Blood tests", "lab", "laboratory"),
    (r"\bscan\b", "Scan", "ct", "imaging"),
]

# Imaging names carry the words that follow the keyword ("CT abdomen and pelvis with contrast").
IMAGING_DETAIL = {"CT", "MRI", "X-ray", "Ultrasound", "Doppler", "Scan"}
DETAIL_STOP = re.compile(
    r"\s+(?:to|for|because|as|in view of|since|if|was|were|is|are|showed|shows|today|tomorrow|"
    r"now|stat|urgently|and\s+(?:repeat|get|send|check))\b|[,.;:(]", re.I)
CANCELLED = re.compile(
    r"\b(?:no need|not needed|not required|not indicated|cancel(?:led)?|avoid|defer(?:red)?|hold off)\b", re.I)
RESULT = re.compile(
    r"\b(?:was|were|showed|shows|revealed|reveals|reported|normal|unremarkable|reviewed|came back)\b"
    r"|(?<!be )\bdone\b", re.I)
AGAIN = re.compile(r"\b(?:repeat|recheck|again)\b", re.I)
URGENT = re.compile(r"\b(?:stat|urgent(?:ly)?|immediately|today|asap|now)\b", re.I)


def _detail(rest: str) -> str:
    stop = DETAIL_STOP.search(rest)
    words = (rest[: stop.start()] if stop else rest).split()[:6]
    text = " ".join(words)
    return re.sub(r"^(?:scan\s+)?(?:of\s+(?:the\s+)?)?", "", text, flags=re.I)


def _studies(sentence: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    taken: list[tuple[int, int]] = []
    for pattern, label, category, kind in STUDIES:
        for m in re.finditer(pattern, sentence, re.I):
            if any(m.start() < end and m.end() > start for start, end in taken):
                continue
            # "CT scan" is one study: the generic "scan" counts only when no named imaging was found.
            if label == "Scan" and any(k == "imaging" for _, _, k in found):
                continue
            if label in IMAGING_DETAIL:
                name = f"{label} {_detail(sentence[m.end():])}".strip()
                name = re.sub(r"\bkub\b", "KUB", name, flags=re.I)
            elif label == "Culture":
                name = m.group(0).strip().capitalize()
            else:
                name = label
            found.append((name, category, kind))
            taken.append((m.start(), m.end()))
    return found


def find_orders(sentences: list[str]) -> list[dict[str, Any]]:
    """Return one order per study asked for, with the sentence it came from."""
    orders: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, sentence in enumerate(sentences):
        text = (sentence or "").strip()
        if not text:
            continue
        studies = _studies(text)
        if not studies or CANCELLED.search(text):
            continue
        if RESULT.search(text) and not AGAIN.search(text):
            continue
        for name, category, kind in studies:
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            orders.append({
                "sentence_index": index,
                "sentence": text,
                "study": name,
                "category": category,
                "request_type": kind,
                "priority": "urgent" if URGENT.search(text) else "routine",
            })
    return orders
