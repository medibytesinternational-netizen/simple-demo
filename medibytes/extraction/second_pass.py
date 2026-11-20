"""Union of rows the small-int8 second pass heard and MedASR missed."""
import re

from .entities import extract_entities
from .normalize import normalize_text
from .vitals import vital_span_kind


def union_second_pass(primary, second_text, second_model, segments):
    """Add drug and vital rows a second decoder heard and the primary missed.

    The decoders fail on different words. Measured on the 23 held-out clips,
    `medasr` recovers 14 of 24 gold drugs and `small-int8` 15, but their union
    is 20 - six drugs exist in one transcript and not the other, which is a
    bigger gap than any single-decoder change has produced.

    Drugs are unioned and vitals are not, and that asymmetry is the whole
    design. A drug name is a discrete thing: if either decoder heard
    `ondansetron`, something was said, and de-duplicating on the canonical
    name keeps the list clean - the union added **zero** spurious drug rows.
    Vitals are a number plus a span of prose, so the same reading comes back
    as "pulse is 102" from one decoder and "pulse 102" from the other; the
    union could not tell those apart and produced 44 spurious spans against
    12. So the second pass contributes drug rows only.

    A row that only one decoder heard is weaker evidence than one they agree
    on, so it is never GREEN and it names the decoder that found it.
    """
    known = {str(d.get("name", "")).lower() for d in primary.get("drugs", [])}
    extra = extract_entities(second_text, normalize_text(second_text)["normalized_en"],
                             segments)
    added = []
    for row in extra.get("drugs", []):
        name = str(row.get("name", "")).lower()
        if not name or name in known:
            continue
        known.add(name)
        row = dict(row)
        row["confidence"] = min(float(row.get("confidence", 0.70)), 0.70)
        row["color"] = "RED" if row.get("color") == "RED" else "YELLOW"
        row["note"] = (f"{row.get('note', '')} | heard only by {second_model}, "
                       f"not by the primary decoder").strip(" |")
        row["second_pass"] = second_model
        added.append(row)
    primary["drugs"] = list(primary.get("drugs", [])) + added
    if added:
        primary["drug_second_pass"] = {"model": second_model,
                                       "added": [r["name"] for r in added]}

    # Vitals too, but keyed on what the reading *is* rather than how it was
    # worded. De-duplicating on the raw span failed because the decoders write
    # the same reading differently - "pulse is 102" against "pulse 102" - so
    # every agreed vital arrived twice and the union produced 44 spurious
    # spans against 12. Keying on (kind, numbers) recognises them as one
    # reading: same +2 facts, 17 spurious instead of 44.
    def _key(span):
        return (vital_span_kind(span), tuple(re.findall(r"\d+(?:\.\d+)?", span)))

    seen = {_key(v.get("text", "")) for v in primary.get("vitals", [])}
    v_added = []
    for row in extra.get("vitals", []):
        k = _key(row.get("text", ""))
        if k[0] is None or k in seen:
            continue
        seen.add(k)
        row = dict(row)
        row["confidence"] = min(float(row.get("confidence", 0.87)), 0.70)
        row["note"] = (f"{row.get('note', '')} | heard only by {second_model}, "
                       f"not by the primary decoder").strip(" |")
        row["second_pass"] = second_model
        v_added.append(row)
    primary["vitals"] = list(primary.get("vitals", [])) + v_added
    if v_added:
        primary.setdefault("drug_second_pass", {})["vitals_added"] = len(v_added)
    return primary
