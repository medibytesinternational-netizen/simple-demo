"""Registration intake: pre-fill a new patient's details from the consultation recording or an old
prescription / discharge summary, before the patient exists.

The file is held under ``uploads/intake/<id>/`` until registration. Nothing found here is saved as
patient data until a person checks it on the form and registers. At registration the intake is
attached: the document becomes the patient's document (read again and confirmed as usual), and the
recording becomes the consent record, the transcript and the OPD draft.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from pathlib import Path
from typing import Any

from ..config import settings

DOC_TYPES = ("prescription", "discharge_summary")
FIELDS = ("name", "age", "sex", "phone", "address", "allergies", "problems")


# ------------------------------------------------------------------ storage

def _dir(intake_id: str) -> Path:
    if not re.fullmatch(r"itk_[0-9a-f]{12}", intake_id or ""):
        raise KeyError(intake_id)
    return settings.uploads_dir / "intake" / intake_id


def create(kind: str, filename: str, mime: str, contents: bytes, **extra: Any) -> dict[str, Any]:
    intake_id = f"itk_{uuid.uuid4().hex[:12]}"
    folder = _dir(intake_id)
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename or "upload").name)[:80] or "upload"
    path = folder / safe
    path.write_bytes(contents)
    meta = {"id": intake_id, "kind": kind, "filename": filename, "mime": mime, "path": str(path), "status": "pending", **extra}
    save(meta)
    return meta


def load(intake_id: str) -> dict[str, Any]:
    try:
        meta_path = _dir(intake_id) / "meta.json"
    except KeyError:
        raise KeyError(intake_id) from None
    if not meta_path.is_file():
        raise KeyError(intake_id)
    return json.loads(meta_path.read_text(encoding="utf-8"))


def save(meta: dict[str, Any]) -> None:
    (_dir(meta["id"]) / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


# ------------------------------------------------------------------ reading text

def document_text(path: Path, mime: str) -> str:
    from .ocr import _pdf_text

    if mime == "application/pdf" or path.suffix.lower() == ".pdf":
        return _pdf_text(path)
    return ""


_RX_LINE = re.compile(r"^\s*(?:\d+[.)]\s*)?(?:tab|tablet|cap|capsule|syp|syrup|inj|injection|oint|drops?)\b\.?\s", re.I | re.M)


def guess_doc_type(text: str, filename: str = "") -> str:
    """prescription or discharge_summary, from what the document says (and its name as a hint)."""
    lowered = (text or "").lower()
    name = filename.lower()
    if "discharge" in lowered or "discharge" in name:
        return "discharge_summary"
    if len(_RX_LINE.findall(text or "")) >= 1 or "prescription" in lowered or "rx" in name or "prescription" in name:
        return "prescription"
    return "discharge_summary"


# ------------------------------------------------------------------ extraction

def _field(value: Any, confidence: float, source: str = "") -> dict[str, Any]:
    return {"value": value, "confidence": round(confidence, 2), "source": source.strip()[:160]}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" .,:;-")


def _split(text: str) -> list[str]:
    return [_clean(p) for p in re.split(r"[,;]|\band\b", text) if _clean(p)]


_NONE = re.compile(r"^(nil|none|no|nkda|nka|no known( drug)? allerg(y|ies))\b", re.I)
_SEX = {"m": "Male", "male": "Male", "f": "Female", "female": "Female", "o": "Other", "other": "Other"}


def _allergies(raw: str, source: str, fields: dict[str, Any]) -> None:
    raw = _clean(raw)
    if not raw:
        return
    if _NONE.match(raw):
        fields["allergies"] = _field([], 0.85, source)
        fields["no_known_allergies"] = _field(True, 0.85, source)
    else:
        fields["allergies"] = _field(_split(raw), 0.8, source)


def parse_document(text: str) -> dict[str, Any]:
    """Labelled lines from a prescription or discharge summary ('Name: ...', 'Age/Sex: 34/F' ...)."""
    fields: dict[str, Any] = {}
    for line in (ln.strip() for ln in text.splitlines()):
        if not line:
            continue
        if "name" not in fields and (m := re.search(r"\b(?:patient(?:'s)?\s+)?name\s*[:\-]\s*(?:(?:mrs|miss|master|mr|ms|dr)\b\.?\s*)?([A-Za-z][A-Za-z .'-]{1,60}?)(?=\s{2,}|\s+(?:age|sex|gender|mrn|uhid|ip|op|date)\b|$)", line, re.I)):
            fields["name"] = _field(_clean(m.group(1)).title(), 0.85, line)
        if (m := re.search(r"\bage\s*/\s*(?:sex|gender)\s*[:\-]?\s*(\d{1,3})\s*(?:y(?:rs?|ears?)?)?\s*/\s*([MFO]|male|female|other)\b", line, re.I)):
            fields.setdefault("age", _field(int(m.group(1)), 0.85, line))
            fields.setdefault("sex", _field(_SEX[m.group(2).lower()], 0.85, line))
        if "age" not in fields and (m := re.search(r"\bage\s*[:\-]?\s*(\d{1,3})\b", line, re.I)):
            fields["age"] = _field(int(m.group(1)), 0.85, line)
        if "sex" not in fields and (m := re.search(r"\b(?:sex|gender)\s*[:\-]?\s*(male|female|other|[MFO])\b", line, re.I)):
            fields["sex"] = _field(_SEX[m.group(1).lower()], 0.85, line)
        if "phone" not in fields and (m := re.search(r"\b(?:phone|mobile|mob|contact|tel)\b\.?\s*(?:no\.?)?\s*[:\-]?\s*(\+?\d[\d \-]{6,17}\d)", line, re.I)):
            fields["phone"] = _field(_clean(m.group(1)), 0.8, line)
        if "address" not in fields and (m := re.search(r"\baddress\s*[:\-]\s*(.+)", line, re.I)):
            fields["address"] = _field(_clean(m.group(1)), 0.7, line)
        if "allergies" not in fields and (m := re.search(r"\ballerg(?:y|ies)\b\s*(?:to)?\s*[:\-]\s*(.+)", line, re.I)):
            _allergies(m.group(1), line, fields)
        if (m := re.search(r"\b(?:diagnos[ie]s|final diagnosis|provisional diagnosis|known case of|k/c/o|past history|co-?morbidities|problems?)\b\s*[:\-]\s*(.+)", line, re.I)):
            current = fields.get("problems", {}).get("value", [])
            fields["problems"] = _field(current + [p for p in _split(m.group(1)) if p not in current], 0.75, line)
    return fields


_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}


def parse_transcript(text: str) -> dict[str, Any]:
    """What the patient said about themselves ('my name is ...', 'I am 34 years old', 'allergic to ...')."""
    fields: dict[str, Any] = {}
    for sentence in re.split(r"(?<=[.?!])\s+|\n", text):
        s = sentence.strip()
        if not s:
            continue
        if "name" not in fields and (m := re.search(r"\b(?:my name is|i am called|this is|name is)\s+([A-Z][a-zA-Z'-]+(?:\s+[A-Z][a-zA-Z'-]+){0,3})", s)):
            fields["name"] = _field(_clean(m.group(1)), 0.7, s)
        if "age" not in fields and (m := re.search(r"\b(\d{1,3})\s*(?:years?|yrs?)(?:\s*old)?\b", s, re.I)):
            fields["age"] = _field(int(m.group(1)), 0.7, s)
        if "sex" not in fields and (m := re.search(r"\b(male|female|man|woman|boy|girl)\b", s, re.I)):
            word = m.group(1).lower()
            fields["sex"] = _field("Male" if word in {"male", "man", "boy"} else "Female", 0.6, s)
        if "phone" not in fields and (m := re.search(r"\b(?:phone|mobile|number)\b[^0-9+]{0,20}(\+?\d[\d \-]{6,17}\d)", s, re.I)):
            fields["phone"] = _field(_clean(m.group(1)), 0.6, s)
        if "allergies" not in fields:
            if re.search(r"\bno (?:known )?(?:drug )?allerg(?:y|ies)\b|\bnot allergic\b", s, re.I):
                _allergies("none", s, fields)
            elif (m := re.search(r"\ballergic to\s+([a-zA-Z ,-]+)", s, re.I)):
                _allergies(m.group(1), s, fields)
        if (m := re.search(r"\b(?:i have|i've got|known case of|history of|i suffer from)\s+(diabetes|hypertension|high blood pressure|asthma|thyroid|copd|heart disease|kidney disease)\b", s, re.I)):
            current = fields.get("problems", {}).get("value", [])
            problem = m.group(1).capitalize()
            if problem not in current:
                fields["problems"] = _field(current + [problem], 0.6, s)
    return fields


def _live(text: str, image: tuple[bytes, str] | None, kind: str) -> dict[str, Any] | None:
    """Model extraction when a key is set; values must come from the source, else they are left out."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    source = "consultation transcript" if kind == "audio" else "previous prescription or discharge summary"
    content: Any
    if image:
        data, mime = image
        content = [
            {"type": "text", "text": f"Extract the patient's details from this {source}."},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"}},
        ]
    else:
        content = f"Extract the patient's details from this {source}. Treat it as the only source.\n\n{text[:20000]}"
    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": (
                "Return JSON {fields: {name, age, sex, phone, address, allergies, no_known_allergies, problems}}. "
                "Each present key is {value, confidence 0-1, source (the exact words it came from)}. "
                "age is an integer in years; sex is Male, Female or Other; allergies and problems are lists. "
                "Leave out anything not stated. Never guess."
            )},
            {"role": "user", "content": content},
        ],
        timeout=60,
    )
    data = json.loads(response.choices[0].message.content or "{}")
    fields = data.get("fields")
    return fields if isinstance(fields, dict) and fields else None


def extract(kind: str, text: str, image: tuple[bytes, str] | None = None) -> tuple[dict[str, Any], str]:
    """(fields, method). Model first when live, else the rule reader."""
    if settings.effective_llm_mode == "live" and (text or image):
        try:
            fields = _live(text, image, kind)
            if fields:
                return {k: v for k, v in fields.items() if isinstance(v, dict) and "value" in v}, "model"
        except Exception:
            pass
    return (parse_transcript(text) if kind == "audio" else parse_document(text)), "rules"
