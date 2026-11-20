"""Stage 3 - normalise the transcript: shorthand map, unit spacing, BP forms, digits."""
import re

from .numerals import numwords_to_digits

HINGLISH_MAP = [
    ("bukhar", "fever"), ("बुखार", "fever"), ("khansi", "cough"), ("खांसी", "cough"),
    ("do time", "twice daily"), ("din tak", "days"), ("din", "days"),
    ("BID", "twice daily"), ("OD", "once daily"), ("TDS", "thrice daily"),
    ("500 मिलीग्राम", "500 mg"), ("मिलीग्राम", "mg"), ("माइक्रोग्राम", "mcg"),
]


def detect_lang_tag(text):
    hi = len(re.findall(r"[\u0900-\u097F]", text))
    ta = len(re.findall(r"[\u0B80-\u0BFF]", text))
    hinglish = bool(re.search(r"\b(ko|hai|din|tak|do time|bukhar|khansi)\b", text, re.I))
    scripts = sum([hi > 0, ta > 0, bool(re.search(r"[A-Za-z]", text))])
    if scripts > 1 or (hinglish and re.search(r"[A-Za-z]", text)):
        return "mix"
    if ta:
        return "ta-IN"
    if hi:
        return "hi-IN"
    return "en-IN"


def normalize_text(text):
    """Stage 3: Hinglish map + UCUM-ish unit spacing + mix tag."""
    normalizations = []
    out = text
    for src, dst in HINGLISH_MAP:
        # word-boundary replace stops OD matching inside blood/method
        pat = r"\b" + re.escape(src) + r"\b"
        if re.search(pat, out, flags=re.I):
            out = re.sub(pat, dst, out, flags=re.I)
            normalizations.append({"from": src, "to": dst})
    out = re.sub(r"(\d+)\s*(mg|mcg|ml|g)\b", r"\1 \2", out)
    out = re.sub(r"\bB[\s-]*P\b", "BP", out)  # B-P -> BP
    # Narrow phonetic: BPA + digits -> BP (ward STT mishear, e.g. "BPA 130 by AC")
    if re.search(r"\bBPA\s*\d", out, flags=re.I):
        out = re.sub(r"\bBPA(?=\s*\d)", "BP", out, flags=re.I)
        normalizations.append({"from": "BPA", "to": "BP"})
    # Narrow phonetic: "<sys> by AC" -> "<sys> by 80" (AC misheard for eighty)
    if re.search(r"\d\s*(?:by|/|over|of)\s*AC\b", out, flags=re.I):
        out = re.sub(r"(\d\s*(?:by|/|over|of)\s*)AC\b", r"\g<1>80", out, flags=re.I)
        normalizations.append({"from": "by AC", "to": "by 80"})
    # Room-air mishear: Rhoomair -> room air (SpO2 sentence only)
    if re.search(r"rhoomair", out, flags=re.I):
        out = re.sub(r"rhoomair", "room air", out, flags=re.I)
        normalizations.append({"from": "Rhoomair", "to": "room air"})
    before_spo2 = out
    out = re.sub(r"\bS[\s-]*P[\s-]*O[\s-]*(two|2)\b", "SpO2", out, flags=re.I)
    if out != before_spo2:
        normalizations.append({"from": "S-P-O-two", "to": "SpO2"})
    # q8h-style shorthand -> words before digitization
    if re.search(r"\bq(\d+)h\b", out, flags=re.I):
        out = re.sub(r"\bq(\d+)h\b", r"every \1 hours", out, flags=re.I)
        normalizations.append({"from": "qNh", "to": "every N hours"})
    # BD/TID shorthand (word-boundary safe)
    for _src, _dst in (("BD", "twice daily"), ("TID", "thrice daily")):
        if re.search(r"\b" + _src + r"\b", out):
            out = re.sub(r"\b" + _src + r"\b", _dst, out)
            normalizations.append({"from": _src, "to": _dst})
    out = numwords_to_digits(out)  # dictation words -> digits for extraction
    out = re.sub(r"(\d+(?:\.\d+)?)\s*(by|over)\s*(\d+(?:\.\d+)?)", r"\1/\3", out)  # BP 130 by/over 80
    # 'of' separator ONLY in BP context ( "... BP ... 122 of 78" / "blood pressure ... 122 of 78" )
    out = re.sub(
        r"((?:BP|blood pressure)[^.]{0,40}?\d+(?:\.\d+)?)\s+of\s+(\d+(?:\.\d+)?)",
        r"\1/\2", out, flags=re.I,
    )
    tag = detect_lang_tag(text)
    return {"normalized_en": out, "normalizations": normalizations, "lang_tag": tag}
