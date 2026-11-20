"""Stage 7 - the 6-section discharge note (heard-only, proof-grounded).

gpt-4.1 takes the transcript plus the deterministic `verify` facts and authors
ONLY the six sections. Then, deterministically:

* `gate_discharge` drops any item without a verbatim proof sentence, with a
  number the transcript never contained, or naming an unknown medicine;
* `canonicalize_discharge` makes verified facts own their entities (drug name,
  dose, vital span) and drops orphan lines unless they are purely extractive;
* `merge_discharge` guarantees every gate-passable verified fact appears once;
* `complete_coverage` flags dictated sections left empty and asks once more
  for just those (the reply passes the same gate and canonicalize);
* `stamp_schema` records Draft-7 conformance against `schemas/discharge.schema.json`.
"""
import json
import re

from jsonschema import Draft7Validator

from ..config import C1, SCHEMAS_DIR
from ..errors import LLMError, LLMTimeout, LLMUnavailable
from ..extraction.negation import NEG_PAT, negated_before
from ..extraction.vocabulary import load_drug_list
from ..ports import LLMClient
from ..reference import drug_reference
from ..verify import _sentences
from .json_reply import extract_json_object

from ..templates import DISCHARGE, NoteTemplate
from ..templates.discharge import PREFILL_SECTION, SECTION_EXAMPLES, SECTION_RULES  # noqa: F401

# Every function below takes ``template`` (default: the measured discharge note).
# A feature template's section is hardened by the rules of the discharge section it
# ``behaves_like``; see medibytes/templates/base.py.
DISCHARGE_SECTIONS = DISCHARGE.keys


def _seg_hint(source_sentence, segments):
    """Segment index containing this proof sentence, or None."""
    sent = str(source_sentence or "").strip()
    if not sent:
        return None
    for seg in segments or []:
        if isinstance(seg, dict) and sent in str(seg.get("text", "")):
            return seg.get("id")
    return None


MAX_PROMPT_FACTS = C1.llm.discharge_max_facts


def _fact_index(verified):
    """[(fact_id, fact)] for the non-rejected facts the prompt shows, in order.

    The id is how the model says WHICH fact an item places. Without it the
    only link back was the proof sentence, and one sentence routinely holds
    BP, pulse and RR - so canonicalize could not tell them apart and dropped
    the item. Shared by the prompt and canonicalize so the ids always agree.
    """
    facts = [f for f in (verified or {}).get("facts", []) if f.get("status") != "rejected"]
    return [(f"F{i}", f) for i, f in enumerate(facts[:MAX_PROMPT_FACTS], 1)]


def _verified_lines(verified, segments=None, template: NoteTemplate = DISCHARGE):
    """Verified-fact lines with FULL proof sentences and seg hints.

    Proof is never truncated: the authenticity gate requires a verbatim
    transcript substring, so a cut sentence would guarantee a drop.
    """
    lines = []
    for fid, f in _fact_index(verified):
        src = str(f.get("source_sentence", "") or "")
        seg = _seg_hint(src, segments)
        tag = f"seg={seg}" if isinstance(seg, int) else "seg=?"
        target = template.prefill.get(f.get("kind", ""), "?")
        if f["kind"] == "drug":
            dose = f"{f['dose']} {f.get('unit') or ''}".strip() if f.get("dose") not in (None, "") else "no dose"
            neg = "NOT GIVEN " if f.get("negated") else ""
            brand = next((c for c in f.get("checks", []) if c.startswith("brand:")), "")
            status = f"{f['status']}, {brand}" if brand else f["status"]
            lines.append(f"- {fid} drug -> {target}: {neg}{f['name']} {dose} [{status}, {tag}] <<{src}>>")
        elif f["kind"] == "vital":
            lines.append(f"- {fid} vital -> {target}: {f.get('text')} [{f['status']}, {tag}] <<{src}>>")
        elif f["kind"] == "allergy":
            lines.append(f"- {fid} allergy -> {target}: {'DENIED ' if f.get('negated') else ''}{f.get('text')} [{f['status']}, {tag}] <<{src}>>")
        else:
            neg = "DENIED " if f.get("negated") else ""
            lines.append(f"- {fid} {f['kind']} -> {target}: {neg}{f.get('text', '')} [{f['status']}, {tag}] <<{src}>>")
    return "\n".join(lines)


# Small talk states no fact: the example that yields no item at all.
SMALL_TALK_EXAMPLE = "Okay, thank you for coming in today, it was good to see you."

_EXAMPLE_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")


def _left_out(sentence, item):
    """The runs of sentence words the item dropped, in spoken order."""
    import difflib

    said = _EXAMPLE_WORD.findall(sentence)
    kept = [w.lower() for w in _EXAMPLE_WORD.findall(item)]
    ops = difflib.SequenceMatcher(None, [w.lower() for w in said], kept, autojunk=False).get_opcodes()
    return [" ".join(said[i1:i2]) for tag, i1, i2, _, _ in ops if tag in ("delete", "replace")]


def _example_line(key, template: NoteTemplate = DISCHARGE):
    sentence, item = template.example(key)
    return (f'- {key}: "{item}"\n'
            f'    heard as: "{sentence}"\n'
            f'    left out: {" | ".join(_left_out(sentence, item))}\n')


def _examples_block(keys, template: NoteTemplate = DISCHARGE):
    return ("Example items (a DIFFERENT patient - shows the style only; never copy its content):\n"
            + "".join(_example_line(k, template) for k in keys)
            + f'- no item: heard as: "{SMALL_TALK_EXAMPLE}" - nothing clinical, leave it out\n\n')


# Kept facts are trimmed, never reworded: canonicalize drops any word not said.
# Stated as a concrete bad/good pair - gpt-4.1 kept copying whole clauses
# ("start you on a short course of ...") when told only to "leave out filler".
TRIM_RULE = ("- Keep only the words that state the clinical fact. Leave out filler (so, um, okay), "
             "the speaker addressing the patient (I want you to, we are going to, start you on, "
             "referring you to, stick to, try to), reasons (to help ..., to get ...) and asides. "
             "Every word you keep must be a word the speaker said.\n"
             "- Start each item with the fact itself, as a chart line, usually 2-10 words. "
             'BAD: "we are going to go ahead and increase her Omeprazole to 20 mg daily". '
             'GOOD: "Increase Omeprazole to 20 mg daily".\n')


# The plan and diet are dictated last; a 2,000-character cut lost them on
# longer dictations. 6,000 covers every clip in the corpus.
PROMPT_TRANSCRIPT_CHARS = C1.llm.discharge_transcript_chars


def _parts_block(parts):
    """The analysis checklist, stated to the note author."""
    if not parts:
        return ""
    lines = "".join(f'- {p["section"]}: "{p["quote"]}"\n' for p in parts)
    return ("DICTATED PARTS (found in the transcript; EACH must appear in the note as at least "
            "one item, with source_sentence = the transcript sentence that contains it):\n"
            f"{lines}\n")


def _has_diet(template):
    return any(template.base(k) == "diet_instructions" for k in template.keys)


def _discharge_prompt(transcript_text, normalized_en, verified, segments, parts=None,
                      template: NoteTemplate = DISCHARGE):
    return (
        template.intro + "\n"
        "Copy EVERY fact from the VERIFIED list into its mapped section below.\n"
        "Return STRICT JSON only (no prose, no markdown).\n"
        "Schema:\n"
        + template.schema_line +
        "Section map (follow exactly):\n"
        + "".join(f"- {k}: {template.rule(k)}\n" for k in template.keys) + "\n"
        + _examples_block(template.keys, template) +
        "Rules (must follow):\n"
        "- Output ONLY values heard in the transcript. NEVER invent vitals, drugs, doses, diagnoses, or advice.\n"
        "- Cover every VERIFIED fact below: verified and needs_review facts MUST appear; rejected ones are absent.\n"
        "- If a section has no dictated facts, use empty items []."
        + (" Diet stays EMPTY unless diet was spoken." if _has_diet(template) else "") + "\n"
        "- Drug names, doses and units MUST match the VERIFIED list verbatim (verified values win any conflict).\n"
        "- source_sentence MUST be copied EXACTLY as shown in <<...>> (verbatim transcript substring).\n"
        "- seg_id: copy the seg=N hint from the fact line; use null only for seg=? items.\n"
        "- Doses numeric with UCUM units (mg/mcg/g/ml/U).\n"
        "- ONE fact per item: each vital is its own item (never merge BP, pulse and RR into one item).\n"
        "- For a VERIFIED fact: set fact_id to its id (F1, F2, ...) and copy its text exactly as listed.\n"
        "- The VERIFIED list is NOT complete. You MUST also add every other fact spoken in the "
        "transcript: each symptom with its duration, each examination finding, past history, "
        "plan items such as referrals, therapy, tests or a medicine class with no name or dose, "
        "and every diet and advice line. Use fact_id null and ONLY words from their source "
        "sentence.\n"
        "- Never add an item that a no/denies/without/not denies. A 'not' elsewhere in the "
        "sentence (e.g. 'call if it does not improve') is fine.\n"
        "- source_sentence must be copied exactly as it appears in the transcript, even if "
        "misspelled. In item text, use only the speaker's words, and only those that state the "
        "fact; you may fix an obvious misspelling of a single word, but never add words that "
        "were not said.\n"
        + TRIM_RULE + template.extra_rules + "\n"
        f"VERIFIED FACTS:\n{_verified_lines(verified, segments, template) or '(none)'}\n\n"
        + _parts_block(parts) +
        f"Transcript:\n{transcript_text[:PROMPT_TRANSCRIPT_CHARS]}\n\n"
        f"Normalized:\n{normalized_en[:PROMPT_TRANSCRIPT_CHARS]}"
    )


_COUNT = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
          9: "nine", 10: "ten"}


def _analyse_prompt(transcript_text, template: NoteTemplate = DISCHARGE):
    return (
        f"You are a clinical scribe reading a dictated {template.document}. List EVERY clinical\n"
        "statement the speaker makes, in the order spoken, with the note section it belongs to.\n"
        "Return STRICT JSON only (no prose, no markdown):\n"
        '{"parts": [{"quote": "...", "section": "..."}]}\n\n'
        "Sections:\n"
        + "".join(f"- {k}: {template.rule(k)}\n" for k in template.keys) + "\n"
        "Rules (must follow):\n"
        "- quote MUST be copied EXACTLY from the transcript - a verbatim substring, misspellings\n"
        "  included - and be the shortest stretch that states one fact.\n"
        "- One fact per part: split a list (\"avoid X, take Y, call Z\") into separate parts.\n"
        "- Skip small talk, greetings, section headings (\"for the plan\") and statements that\n"
        "  only deny something (\"no fever\", \"denies chest pain\").\n"
        f"- section MUST be one of the {_COUNT.get(len(template.keys), len(template.keys))} names above.\n\n"
        f"Transcript:\n{transcript_text[:PROMPT_TRANSCRIPT_CHARS]}"
    )


def analyse_transcript(transcript_text, llm: LLMClient, timeout=None,
                       template: NoteTemplate = DISCHARGE):
    """gpt-4.1 lists the dictated parts: [{"quote", "section"}], in spoken order.

    The checklist the note is written and checked against, so a section is
    found from what was said, not from a keyword list that only knows wording
    seen before. A part survives only if its quote is a verbatim transcript
    substring and its section is one of the six: the model cannot invent one.
    Raises on a failed call or an unusable reply; the caller falls back to
    `SECTION_CUES`.
    """
    ok, reason = llm.available()
    if not ok:
        raise LLMUnavailable(reason)
    out = llm.complete_json(_analyse_prompt(transcript_text, template),
                            timeout=timeout or C1.llm.discharge_timeout_s,
                            max_tokens=C1.llm.discharge_max_tokens, stage="discharge_analyse")
    json_str = extract_json_object(out)
    reply = json.loads(json_str) if json_str else None
    if not isinstance(reply, dict) or not isinstance(reply.get("parts"), list):
        raise ValueError("no parts list in the analysis reply")
    parts, seen = [], set()
    for p in reply["parts"]:
        if not isinstance(p, dict):
            continue
        quote = str(p.get("quote", "") or "").strip()
        section = str(p.get("section", "") or "").strip()
        if len(quote) < 3 or section not in template.keys or quote not in transcript_text:
            continue
        if (section, quote) not in seen:
            seen.add((section, quote))
            parts.append({"quote": quote, "section": section})
    return parts


def extract_discharge(transcript_text, normalized_en, segments, verified,
                      llm: LLMClient, timeout=None, parts=None,
                      template: NoteTemplate = DISCHARGE):
    """Author the 6-section note with gpt-4.1.

    Up to three attempts when the reply is not usable JSON. A timeout is not
    retried: the same prompt would only time out again. `parts` (from
    `analyse_transcript`) is the checklist every item must come from.
    """
    timeout = timeout or C1.llm.discharge_timeout_s
    ok, reason = llm.available()
    if not ok:
        raise LLMUnavailable(reason)
    last_error = None
    for _ in range(3):
        try:
            out = llm.complete_json(
                _discharge_prompt(transcript_text, normalized_en, verified, segments, parts, template),
                timeout=timeout, max_tokens=C1.llm.discharge_max_tokens, stage="discharge")
        except (LLMTimeout, LLMUnavailable):
            raise
        except ValueError as e:
            last_error = e
            continue
        json_str = extract_json_object(out)
        if not json_str:
            last_error = ValueError("no JSON in LLM discharge output")
            continue
        try:
            j = json.loads(json_str)
        except Exception as e:
            last_error = ValueError(f"LLM discharge JSON unparsable: {e}")
            continue
        if not isinstance(j, dict) or not any(k in j for k in template.keys):
            last_error = ValueError("LLM discharge JSON missing section keys")
            continue
        return {"sections": _parse_sections(j, template=template),
                "provenance": {"llm_engine": f"{template.name}:{llm.model}"}}
    raise last_error or ValueError("LLM discharge failed after retries")


def _parse_sections(j, keys=None, template: NoteTemplate = DISCHARGE):
    """{section: {"items": [...]}} from a model reply, every item normalised."""
    keys = template.keys if keys is None else keys
    sections = {}
    for key in template.keys:
        block = (j.get(key) or {}) if key in keys else {}
        items = block.get("items", []) if isinstance(block, dict) else []
        clean = []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict) or not str(it.get("text", "")).strip():
                continue
            try:
                conf = float(it.get("confidence", 0.9))
            except (TypeError, ValueError):
                conf = 0.9
            seg = it.get("seg_id")
            seg = seg if isinstance(seg, int) else None
            row = {"text": str(it["text"]).strip(),
                   "source_sentence": str(it.get("source_sentence", "") or ""),
                   "seg_id": seg, "confidence": conf}
            if isinstance(it.get("fact_id"), str) and it["fact_id"].strip():
                row["fact_id"] = it["fact_id"].strip()
            for extra in template.item_extras:
                if it.get(extra) not in (None, ""):
                    row[extra] = it[extra]
            clean.append(row)
        sections[key] = {"items": clean}
    return sections


def _containing_sentence(source, transcript_text, normalized_en):
    """The whole transcript sentence a proof quote sits in (else the quote).

    A proof may be a fragment ("chest discomfort"); judged alone it hides the
    "no history of asthma or" that denies it. Canonicalize scopes negation
    over this sentence, never over the fragment.
    """
    for view in (transcript_text, normalized_en):
        for s in _sentences(view):
            if source in s:
                return s
    return source


def gate_discharge(discharge, transcript_text, normalized_en, verified,
                   template: NoteTemplate = DISCHARGE):
    """Authenticity gate: drop unproven items, cap the rest. Deterministic.

    An item survives only if (a) its source_sentence is a verbatim transcript
    substring, (b) every digit-group in its text occurs in the transcript, and
    (c) every drug name it mentions resolves via the mini-list or reference.
    Survivors keep ``min(confidence, 0.88)``; failures are counted, not fixed.
    """
    full = f"{transcript_text} {normalized_en}"
    known = {d["name"].lower() for d in load_drug_list()}
    for d in load_drug_list():
        for a in [d["name"]] + d.get("aliases", []):
            known.add(str(a).lower())
    verified_names = {str(f.get("name", "")).lower() for f in (verified or {}).get("facts", [])
                      if f.get("kind") == "drug" and f.get("status") != "rejected"}
    dropped = 0
    out_sections = {}
    for key in template.keys:
        items = (discharge.get("sections", {}).get(key, {}) or {}).get("items", []) or []
        kept = []
        for it in items:
            sent = str(it.get("source_sentence", "") or "")
            text = str(it.get("text", "") or "")
            ok = bool(sent) and (sent in transcript_text or sent in normalized_en)
            if ok:
                for num in re.findall(r"\d+(?:\.\d+)?", text):
                    if num not in full:
                        ok = False
                        break
            if ok:
                for word in re.findall(r"[A-Za-z][A-Za-z\-]+", text):
                    w = word.lower()
                    if w in known or w in verified_names:
                        continue
                    rec = drug_reference.lookup(w, block=drug_reference.STOPWORDS, brands=False)
                    if rec:
                        continue
                    # Only police tokens that look like drug mentions: fuzzy
                    # candidates exist AND the extractor flagged the same token.
                    cands = drug_reference.candidates(w)
                    if cands and w not in verified_names:
                        ok = False
                        break
            if ok:
                it = dict(it)
                it["confidence"] = min(float(it.get("confidence", 0.9)), 0.88)
                it["context"] = _containing_sentence(sent, transcript_text, normalized_en)
                kept.append(it)
            else:
                dropped += 1
        out_sections[key] = {"items": kept}
    prov = dict(discharge.get("provenance", {}))
    prov["dropped_unproven"] = dropped
    prov["verified_summary"] = (verified or {}).get("summary", {})
    return {"sections": out_sections, "provenance": prov}


_SCHEMA_CACHE: dict = {}


def _discharge_schema(template: NoteTemplate = DISCHARGE):
    """Load the template's schema file once (Draft7, self-checked)."""
    name = template.schema_file
    if not name:
        return template.json_schema()
    if name not in _SCHEMA_CACHE:
        with open(SCHEMAS_DIR / name, encoding="utf-8") as fh:
            _SCHEMA_CACHE[name] = json.load(fh)
    return _SCHEMA_CACHE[name]


def validate_discharge(discharge, template: NoteTemplate = DISCHARGE):
    """(ok, errors): Draft7 conformance of a discharge note.

    Pure function — no LLM, no I/O beyond the cached schema file. Errors
    are human-readable paths (``sections.plan.items[2].text``), capped at 10.
    Raises nothing for unusable input: reports it as an error instead.
    """
    try:
        schema = _discharge_schema(template)
        Draft7Validator.check_schema(schema)
    except Exception as err:
        return False, [f"schema file invalid: {type(err).__name__}: {err}"]
    if not isinstance(discharge, dict):
        return False, ["discharge note is not an object"]
    errors = [f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}"
              for e in Draft7Validator(schema).iter_errors(discharge)]
    return (True, []) if not errors else (False, errors[:10])


def stamp_schema(discharge, template: NoteTemplate = DISCHARGE):
    """Flag-still-ship: record conformance in provenance, never raise.

    Valid notes get ``provenance.schema = "valid"``; invalid ones keep
    their content and get ``provenance.schema = "INVALID"`` plus the first
    error in ``provenance.schema_error`` for the RED review row. Callers
    always write the file either way.
    """
    try:
        ok, errors = validate_discharge(discharge, template)
    except Exception as err:  # validation must never break a run
        ok, errors = False, [f"validator crashed: {type(err).__name__}: {err}"]
    prov = dict(discharge.get("provenance", {}))
    if ok:
        prov["schema"] = "valid"
        prov.pop("schema_error", None)
    else:
        prov["schema"] = "INVALID"
        prov["schema_error"] = errors[0] if errors else "unknown schema error"
    return {"sections": discharge.get("sections", {}), "provenance": prov}


def _prefill_text(fact):
    """Section item text built from one verified fact (heard words only)."""
    kind = fact.get("kind", "")
    if kind == "drug":
        dose = fact.get("dose")
        unit = fact.get("unit") or ""
        if dose is None or dose == "":
            core = f"{fact.get('name', '')} no dose".strip()
        else:
            try:
                core = f"{fact.get('name', '')} {float(dose):g} {unit}".strip()
            except (TypeError, ValueError):
                core = str(fact.get("name", ""))
        if fact.get("negated"):
            core = f"NOT GIVEN: {core}"
        return core
    if kind == "vital":
        return str(fact.get("text", ""))
    if kind == "allergy":
        prefix = "DENIED allergy: " if fact.get("negated") else "Allergy: "
        return prefix + str(fact.get("text", ""))
    if kind == "symptom":
        text = _LEAD_PREP.sub("", str(fact.get("text", "")))
        return f"DENIED: {text}" if fact.get("negated") else text
    if kind == "diagnosis":
        return _LEAD_PREP.sub("", str(fact.get("text", "")))
    return str(fact.get("text", ""))


# The span a diagnosis or symptom rule matched can start at its connective:
# "previous diagnosis of moderate persistent asthma" -> "of moderate ...".
_LEAD_PREP = re.compile(r"^\s*(?:of|with|for)\s+", re.I)


def _prefill_eligible(fact, transcript_text, normalized_en, template: NoteTemplate = DISCHARGE):
    """Gate-identical eligibility: proof verbatim + digits present + mapped."""
    if fact.get("status") == "rejected" or fact.get("kind") not in template.prefill:
        return False
    if fact.get("kind") == "drug" and (fact.get("dose") is None or fact.get("dose") == ""):
        pass  # doseless rows still surface (RED review), proof decides
    src = str(fact.get("source_sentence", "") or "")
    if not src or (src not in transcript_text and src not in normalized_en):
        return False
    full = f"{transcript_text} {normalized_en}"
    text = _prefill_text(fact).replace("NOT GIVEN: ", "").replace("DENIED: ", "").replace(
        "DENIED allergy: ", "").replace("Allergy: ", "")
    for num in re.findall(r"\d+(?:\.\d+)?", text):
        if num not in full:
            return False
    return bool(text.strip())


_NUM = re.compile(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])")


def _covered(fact, fact_text, item):
    """Does this note item already state this verified fact?

    Identity is the fact, not its sentence: one dictated sentence routinely
    carries BP, pulse and RR, and keying on the proof sentence surfaced only
    the first of them. So a vital is covered only by an item reporting the
    same set of numbers (an LLM item merging three vitals does not hide two
    of them), a drug by its name plus its dose plus the same NOT GIVEN
    polarity, and anything else by containing its text with the same DENIED
    polarity - which also collapses one symptom heard in two sentences.
    """
    have = str(item.get("text", "") or "").lower()
    want = str(fact_text or "").lower()
    if not have or not want:
        return False
    kind = fact.get("kind")
    if kind == "vital":
        nums = set(_NUM.findall(want))
        return bool(nums) and set(_NUM.findall(have)) == nums
    if kind == "drug":
        if ("not given" in have) != bool(fact.get("negated")):
            return False
        if str(fact.get("name", "")).lower() not in have:
            return False
        dose = fact.get("dose")
        if dose in (None, ""):
            return True
        try:
            return f"{float(dose):g}" in {f"{float(n):g}" for n in _NUM.findall(have)}
        except (TypeError, ValueError):
            return True
    if ("denied" in have) != ("denied" in want):
        return False
    core = re.sub(r"^(denied( allergy)?|allergy):\s*", "", want).strip()
    return bool(core) and core in have


def merge_discharge(verified, discharge, transcript_text="", normalized_en="",
                    template: NoteTemplate = DISCHARGE):
    """Deterministic pre-fill: every gate-passable verified fact surfaces once.

    Runs after the gate over the gated sections: for each eligible verified
    fact whose text/proof is not already present (case-folded), appends an
    item tagged ``verified_kind``/``verified_status`` with proof verbatim and
    confidence capped (never promoted). Diet is never pre-filled (heard-only:
    only the LLM may assert diet advice, and only with proof).
    """
    sections = {k: {"items": list((discharge.get("sections", {}).get(k, {}) or {}).get("items", []) or [])}
                for k in template.keys}
    prefilled = 0
    for fact in (verified or {}).get("facts", []):
        target = template.prefill.get(fact.get("kind", ""), "")
        if not target or template.base(target) == "diet_instructions":
            continue
        if not _prefill_eligible(fact, transcript_text, normalized_en, template):
            continue
        text = _prefill_text(fact)
        src = str(fact.get("source_sentence", "") or "")
        if any(_covered(fact, text, it) for it in sections[target]["items"]):
            continue
        conf = fact.get("confidence", 0.9)
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = 0.9
        conf = min(conf, 0.88)
        if fact.get("kind") == "vital" and fact.get("status") == "needs_review":
            conf = min(conf, 0.70)
        sections[target]["items"].append({
            "text": text, "source_sentence": src, "seg_id": None,
            "confidence": conf, "verified_kind": fact.get("kind"),
            "verified_status": fact.get("status")})
        prefilled += 1
    provenance = dict(discharge.get("provenance", {}))
    provenance["verified_summary"] = (verified or {}).get("summary", {})
    provenance["prefilled"] = prefilled
    return {"sections": _drop_restatements(sections), "provenance": provenance}


# Words that only announce a section: "previous diagnosis of asthma" says no
# more than "asthma".
_ANNOUNCE = frozenset("previous past history diagnosis diagnosed known case".split())


def _drop_restatements(sections):
    """Drop an LLM-only line that says nothing another line of its section doesn't.

    "previous diagnosis of moderate persistent asthma" beside the verified
    "moderate persistent asthma" is the same fact twice. A line that adds a
    word ("dry cough over the last 10 days" beside "cough") stays.
    """
    out = {}
    for key, block in sections.items():
        items = list((block or {}).get("items", []) or [])
        words = [_content_words(it.get("text", "")) - _ANNOUNCE for it in items]
        kept = []
        for i, it in enumerate(items):
            mine = words[i]
            if "llm-extractive" in str(it.get("note", "")) and mine and any(
                    j != i and mine <= words[j]
                    and ("llm-extractive" not in str(items[j].get("note", ""))
                         or j < i or mine < words[j])
                    for j in range(len(items))):
                continue
            kept.append(it)
        out[key] = {**(block or {}), "items": kept}
    return out


def _proof_group(verified):
    """Verified non-rejected facts keyed by source_sentence."""
    groups: dict[str, list[dict]] = {}
    for f in (verified or {}).get("facts", []):
        if f.get("status") == "rejected":
            continue
        src = str(f.get("source_sentence", "") or "")
        if src:
            groups.setdefault(src, []).append(f)
    return groups


def _closest_drug(item_text, candidates):
    """The verified drug sharing the most name tokens with the LLM text."""
    import difflib

    words = set(re.findall(r"[a-z]+", str(item_text or "").lower()))
    best, best_score = None, 0.0
    for c in candidates:
        name_words = set(str(c.get("name", "")).lower().split())
        overlap = len(words & name_words)
        score = overlap + difflib.SequenceMatcher(
            None, str(item_text or "").lower(), str(c.get("name", "")).lower()).ratio() / 10.0
        if overlap and score > best_score:
            best, best_score = c, score
    return best


def _vital_by_numbers(item_text, cands):
    """The one vital fact whose numbers are exactly this item's, or None.

    One sentence carries BP, pulse and RR; an item reading "pulse 92" is the
    pulse fact because 92 is its whole number set, not because of wording.
    """
    have = set(_NUM.findall(str(item_text or "")))
    if not have:
        return None
    hits = [c for c in cands if c.get("kind") == "vital"
            and set(_NUM.findall(str(c.get("text", "")))) == have]
    return hits[0] if len(hits) == 1 else None


# Sections an LLM-only item may land in. Drugs, doses, verified vitals and
# allergies must come from a verified fact: those are the rows where a wrong
# value is a safety event. The plan takes heard, number-free, drug-free lines
# (a referral, a therapy, "a short course of anti-inflammatories"), and the
# exam takes heard findings the vital extractor has no rule for ("mild
# end-expiratory wheezing on both sides") - without them a dictated plan or
# exam came out empty.
_EXTRACTIVE_SECTIONS = {"present_illness", "examination_findings", "previous_diagnosis",
                        "plan_of_management", "diet_instructions", "general_instructions"}

# Sections whose extractive items are held for review, below the usual cap.
_REVIEW_SECTIONS = {"examination_findings", "plan_of_management"}

# Where an item may fix a misheard word ("greins" -> "greens", "icest" ->
# "chest"); such items are held for review. Never the plan: a fixed word there
# sits next to drugs and doses.
_CORRECTABLE_SECTIONS = {"present_illness", "examination_findings", "previous_diagnosis",
                         "diet_instructions", "general_instructions"}
_CORRECTION_MIN_RATIO = 0.80
_CORRECTION_MIN_LEN = 4

# Sections where an item may carry a number the source sentence states
# ("omega-3", "inhaler 15 minutes before", "crepitus at 40 degrees"). The plan
# never may: a number there is a dose, and doses belong to verified drugs.
_NUMBERED_SECTIONS = {"examination_findings", "diet_instructions", "general_instructions"}

# Present illness takes a number only as a symptom's duration.
_DURATION = re.compile(r"\b\d+(?:\.\d+)?\s*(?:minutes?|hours?|days?|weeks?|months?|years?)\b")


_EXTRACTIVE_STOP = frozenset(
    "a an the and or of in on at to for with his her he she is was has have had "
    "been some also about".split())

_HEARD_WORD = re.compile(r"[a-z][a-z'-]*")


def _heard_view(sentence):
    """The sentence lower-cased, with words the recogniser glued split apart.

    MedASR runs words together at a missed boundary ("useYour inhaler"); the
    split only exposes words that were literally spoken.
    """
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", str(sentence or "")).lower()


def _item_span(words, sent):
    """(start, end) of the first place the item's words occur in order, or None."""
    spans = [(m.start(), m.end(), m.group()) for m in _HEARD_WORD.finditer(sent)]
    for i, (start, end, w) in enumerate(spans):
        if w != words[0]:
            continue
        j = i
        for want in words[1:]:
            j = next((k for k in range(j + 1, len(spans)) if spans[k][2] == want), None)
            if j is None:
                break
            end = spans[j][1]
        else:
            return start, end
    return None


def _item_negated(text, words, sent):
    """Does a negation deny THIS item? Scoped to the clause leading into it.

    The whole-sentence test dropped every item of a run-on instruction that
    ended "... call if your breathing does not improve". Now an item is denied
    when a cue precedes it in its clause (`negated_before`: back to the last
    contrast marker, commas do not break it, so "no history of asthma or chest
    discomfort" still denies "chest discomfort"), or when a cue inside its span
    was left out of the item. An item that carries its own "not" keeps its
    meaning. Words that cannot be located keep the whole-sentence test.
    """
    span = _item_span(words, sent) if words else None
    if span is None:
        return bool(NEG_PAT.search(sent))
    start, end = span
    if negated_before(sent[:start]):
        return True
    return any(not re.search(rf"\b{re.escape(m.group().lower())}\b", text)
               for m in NEG_PAT.finditer(sent[start:end]))


def _near_heard(word, heard):
    """Is `word` a small spelling fix of one heard word (difflib ratio >= 0.80)?"""
    import difflib

    if len(word) < _CORRECTION_MIN_LEN:
        return False
    return any(difflib.SequenceMatcher(None, word, h).ratio() >= _CORRECTION_MIN_RATIO
               for h in heard)


def _extractive_ok(item, section, context=None, template: NoteTemplate = DISCHARGE):
    """May an LLM item with no verified fact stay? "exact", "corrected" or None.

    The extractor has no rule for most symptoms and history ("chest
    discomfort", "hypertension"), so the model is the only stage that can
    place them - and canonicalize used to drop every such item. It keeps one
    only when nothing in it could be wrong in a way the transcript would not
    show: the proof sentence already passed the verbatim gate; the item has
    no digits (numbers belong to verified vitals/doses); every content word
    of the item is a word of that sentence (heard, not paraphrased); no word
    is a medicine; and no negation denies the item (`_item_negated`), so
    "no history of asthma" can never become an "asthma" line. Kept items are
    capped at 0.80, below anything verified.

    `context` is the full transcript sentence around a fragment proof.

    Exam, diet and general instructions may carry a number the sentence says
    ("omega-3", "15 minutes before"); present illness only a duration ("10
    days"). Every section but the plan may also fix a misheard word
    ("greens" for "greins"). Such an item is "corrected" - the model's guess
    at what was said - and is held lower than an exact copy, never higher.
    """
    section = template.base(section)
    if section not in _EXTRACTIVE_SECTIONS:
        return None
    text = str(item.get("text", "") or "").lower()
    sent = _heard_view(item.get("source_sentence", ""))
    if not text or not sent:
        return None
    correctable = section in _CORRECTABLE_SECTIONS
    if re.search(r"\d", text):
        if not set(_NUM.findall(text)) <= set(_NUM.findall(sent)):
            return None
        if section == "present_illness":
            # A symptom's duration ("over the last 10 days") - never a reading.
            if _NUM.findall(_DURATION.sub("", text)):
                return None
        elif section not in _NUMBERED_SECTIONS:
            return None
    words = [w for w in _HEARD_WORD.findall(text) if w not in _EXTRACTIVE_STOP]
    # Negation is judged on the whole sentence the proof sits in (`context`,
    # from the gate): a fragment proof must not hide the cue that denies it.
    if not words or _item_negated(text, words, _heard_view(context) if context else sent):
        return None
    heard = set(_HEARD_WORD.findall(sent))
    corrected = False
    for w in words:
        if w in heard:
            continue
        if correctable and _near_heard(w, heard):
            corrected = True
            continue
        return None
    known = {d["name"].lower() for d in load_drug_list()}
    for w in words:
        if w in known or drug_reference.lookup(w, block=drug_reference.STOPWORDS, brands=False):
            return None
    return "corrected" if corrected else "exact"


_FACT_LABELS = frozenset("denied not given allergy no dose".split())


def _shares_fact(item_text, fact):
    """Does the item mention this fact at all - one content word or one number?

    A sentence that holds one verified fact used to rewrite every item citing
    it into that fact, so "chest tightness" became a second "cough".
    """
    have, want = str(item_text or "").lower(), _prefill_text(fact).lower()
    if set(_NUM.findall(have)) & set(_NUM.findall(want)):
        return True
    words = lambda s: set(_HEARD_WORD.findall(s)) - _EXTRACTIVE_STOP - _FACT_LABELS
    return bool(words(have) & words(want))


# Fact kinds whose text is narrative, so a longer heard line can add to it.
# Drugs and vitals never: their dose and reading come from the verified fact.
_NARRATIVE_KINDS = {"symptom", "diagnosis", "followup"}


def _adds_detail(item_text, fact):
    """Does the line state at least two content words the fact does not?"""
    extra = (_content_words(item_text) - _content_words(_prefill_text(fact))
             - _ANNOUNCE - _FACT_LABELS)
    return len(extra) >= 2


def _as_extractive(it, key, how, template: NoteTemplate = DISCHARGE):
    """The item as an LLM-only line: capped, tagged, held for review where due."""
    it = dict(it)
    it.pop("fact_id", None)
    review = how == "corrected" or template.base(key) in _REVIEW_SECTIONS
    it["confidence"] = min(float(it.get("confidence", 0.9)), 0.70 if review else 0.80)
    tags = " llm-extractive" + (" llm-corrected" if how == "corrected" else "")
    it["note"] = (str(it.get("note", "") or "") + tags).strip()
    if review:
        it["verified_status"] = "needs_review"
    return it


def canonicalize_discharge(discharge, verified, template: NoteTemplate = DISCHARGE):
    """Entity lock-in: LLM lines keep their shape, verified facts own entities.

    For each surviving item, looks up verified facts sharing its proof
    sentence and substitutes canonical surface forms (drug name/dose/unit,
    vital span, allergy/symptom/diagnosis/followup text). Substitutions are
    tagged ``verified_kind``/``verified_status`` plus a ``canonicalized``
    note with confidence capped (never promoted). Items with no matching
    verified fact (ambiguous multi-drug proof, orphan line) are dropped and
    counted — pre-fill still guarantees the verified fact surfaces.
    """
    groups = _proof_group(verified)
    by_id = dict(_fact_index(verified))
    out_sections: dict[str, dict] = {k: {"items": []} for k in template.keys}
    canonicalized = extractive = 0
    dropped = int((discharge.get("provenance", {}) or {}).get("dropped_unproven", 0) or 0)
    for key in template.keys:
        items = (discharge.get("sections", {}).get(key, {}) or {}).get("items", []) or []
        for it in items:
            it = dict(it)
            context = it.pop("context", None)  # set by the gate; not part of the note
            src = str(it.get("source_sentence", "") or "")
            cands = groups.get(src, [])
            target = None
            fid = it.get("fact_id")
            if fid in by_id and str(by_id[fid].get("source_sentence", "") or "") == src:
                target = by_id[fid]  # the model named the fact; proof must agree
            elif cands:
                if len(cands) == 1:
                    target = cands[0]
                else:
                    drugs = [c for c in cands if c.get("kind") == "drug"]
                    target = _closest_drug(it.get("text", ""), drugs) if drugs else None
                    if target is None:
                        target = _vital_by_numbers(it.get("text", ""), cands)
                    if target is None:
                        same_kind = [c for c in cands if template.prefill.get(c.get("kind")) == key]
                        target = same_kind[0] if len(same_kind) == 1 else None
                # Sharing a sentence is not being the same fact: "wheezing" in
                # the sentence that holds the SpO2 reading is its own finding.
                if target is not None and not _shares_fact(it.get("text", ""), target) \
                        and _extractive_ok(it, key, context, template):
                    target = None
            if target is None:
                how = _extractive_ok(it, key, context, template)
                if how:
                    out_sections[key]["items"].append(_as_extractive(it, key, how, template))
                    extractive += 1
                else:
                    dropped += 1
                continue
            # "dry cough and some tightness in her chest over the last 10 days"
            # resolves to the verified "cough"; substituting it would lose the
            # rest. A heard symptom/history line that adds detail stays too.
            if target.get("kind") in _NARRATIVE_KINDS and _adds_detail(it.get("text", ""), target):
                how = _extractive_ok(it, key, context, template)
                if how:
                    out_sections[key]["items"].append(_as_extractive(it, key, how, template))
                    extractive += 1
            # A verified fact lives in its mapped section, whatever the model chose.
            home = template.prefill.get(target.get("kind"), key)
            dest = out_sections[home]["items"]
            canon = _prefill_text(target)
            # Two lines from one sentence can both resolve to the same fact
            # ("budesonide", "continue budesonide with spacer"): state it once.
            if any(str(d.get("text", "")).strip().lower() == canon.strip().lower() for d in dest):
                continue
            if str(it.get("text", "")).strip() == canon:
                it = dict(it)
                it.setdefault("verified_kind", target.get("kind"))
                it.setdefault("verified_status", target.get("status"))
                dest.append(it)
                continue
            it = dict(it)
            it["text"] = canon
            it["verified_kind"] = target.get("kind")
            it["verified_status"] = target.get("status")
            it["confidence"] = min(float(it.get("confidence", 0.9)), 0.88)
            if target.get("kind") == "vital" and target.get("status") == "needs_review":
                it["confidence"] = min(it["confidence"], 0.70)
            note = str(it.get("note", "") or "")
            it["note"] = (note + " canonicalized").strip()
            dest.append(it)
            canonicalized += 1
    provenance = dict(discharge.get("provenance", {}))
    provenance["dropped_unproven"] = dropped
    provenance["canonicalized"] = canonicalized
    provenance["llm_extractive"] = extractive
    return {"sections": out_sections, "provenance": provenance}


# Fallback checklist when the analysis call fails: a sentence that talks about
# a section. Heuristic on purpose - it only asks "was this dictated?" and
# never puts words in the note.
SECTION_CUES = {
    "present_illness": re.compile(
        r"\b(complain\w*|present\w* with|symptom\w*|suffer\w*|pain|aches?)\b", re.I),
    "examination_findings": re.compile(
        r"\b(examin\w*|blood pressure|pulse|temperature|respiratory rate|saturation|spo2|"
        r"heart rate|reflex\w*|tender\w*|auscultation)\b", re.I),
    "previous_diagnosis": re.compile(
        r"\b(history of|diagnos\w*|known case|known to have)\b", re.I),
    "plan_of_management": re.compile(
        r"\b(plan of management|management plan|start you on|going to start|prescrib\w*|"
        r"refer\w*|follow[- ]?up|review after|come back|physiotherapy|physical therapy|"
        r"course of)\b", re.I),
    "diet_instructions": re.compile(
        r"\b(diet\w*|food\w*|eat\w*|meals?|fluids?|drink\w*)\b", re.I),
    "general_instructions": re.compile(
        r"\b(advis\w*|advice|avoid\w*|instruct\w*|call the (?:office|clinic|hospital))\b", re.I),
}


def _cue_parts(transcript_text, template: NoteTemplate = DISCHARGE):
    """The keyword checklist: [{"quote": sentence, "section"}].

    A sentence counts unless a negation comes before its cue word: "No dietary
    restrictions" asks for no diet line, but "... for general instruction ...
    call if it does not improve" is a dictated instruction.
    """
    parts = []
    for s in _sentences(transcript_text):
        for k in _cue_keys(template):
            m = SECTION_CUES[template.base(k)].search(s)
            if m and not negated_before(s[:m.start()]):
                parts.append({"quote": s, "section": k})
    return parts


def _cue_keys(template):
    """One section per discharge cue: the first section that behaves like it."""
    seen, keys = set(), []
    for k in template.keys:
        if template.base(k) not in seen:
            seen.add(template.base(k))
            keys.append(k)
    return keys


def _content_words(text):
    return set(_HEARD_WORD.findall(_heard_view(text))) - _EXTRACTIVE_STOP


def _part_used(part, sections):
    """Did the items taken from this dictated part state at least half of it?

    The items counted are those whose proof overlaps the quote (one contains
    the other), in any section: placement is the author's call, the check only
    asks that nothing said was lost. One shared word is not enough - "cough"
    alone does not cover "dry cough and some tightness in her chest".
    """
    quote = part["quote"]
    want = _content_words(quote)
    if not want:
        return True
    have: set[str] = set()
    numbers: set[str] = set()
    for block in sections.values():
        for it in (block or {}).get("items", []) or []:
            src = str(it.get("source_sentence", "") or "")
            if src and (quote in src or src in quote):
                have |= _content_words(it.get("text", ""))
                numbers |= set(_NUM.findall(str(it.get("text", ""))))
    # A reading is covered when its numbers are: "oxygen level drop great at
    # 98% on room air" is the "98% on room air" vital, misheard filler aside.
    if set(_NUM.findall(quote)) and set(_NUM.findall(quote)) <= numbers:
        return True
    hit = sum(1 for w in want if w in have or _near_heard(w, have))
    return hit * 2 >= len(want)


def check_coverage(note, transcript_text, parts=None, template: NoteTemplate = DISCHARGE):
    """Record which dictated parts the note left out. Never edits items.

    ``stamp_schema`` only proves the note has the right shape: an empty plan
    is still "valid". The checklist is the analysis pass (`parts`) or, when
    that failed, the keyword cues. ``coverage.unused`` lists the parts no
    item came from; ``coverage.missing`` the sections with parts but no item.
    """
    source = "analysis" if parts is not None else "cues"
    checklist = parts if parts is not None else _cue_parts(transcript_text, template)
    sections = note.get("sections", {})
    unused: dict[str, list[str]] = {}
    for p in checklist:
        if not _part_used(p, sections):
            unused.setdefault(p["section"], []).append(p["quote"])
    dictated = {k: sum(p["section"] == k for p in checklist) for k in template.keys}
    missing = [k for k in template.keys
               if dictated[k] and not (sections.get(k, {}) or {}).get("items")]
    prov = dict(note.get("provenance", {}))
    coverage = dict(prov.get("coverage") or {})
    coverage.update({"source": source, "dictated": dictated, "missing": missing,
                     "unused": unused})
    prov["coverage"] = coverage
    return {"sections": sections, "provenance": prov}


def _coverage_prompt(unused, transcript_text, template: NoteTemplate = DISCHARGE):
    blocks = "\n".join(
        f"{k}: {template.rule(k)}\n"
        + "".join(f'  part: "{q}"\n    in sentence: <<{_containing_sentence(q, transcript_text, "")}>>\n'
                  for q in quotes)
        for k, quotes in unused.items())
    return (
        "You are a clinical scribe completing a dictated note. The parts below were\n"
        "dictated but are not in the note yet. Write the items for each one.\n"
        "Return STRICT JSON only (no prose, no markdown):\n"
        '{"<section>": {"items": [{"text": "...", "source_sentence": "exact sentence", "confidence": 0.9}]}}\n\n'
        "Rules (must follow):\n"
        "- source_sentence MUST be copied EXACTLY as shown in <<...>>, even if misspelled.\n"
        "- In item text, use only the speaker's words, and only those that state the fact;\n"
        "  you may fix an obvious misspelling of a single word, but never add words that\n"
        "  were not said.\n"
        + TRIM_RULE +
        "- Never write a drug name, dose or number the sentence does not state.\n"
        "- A part may not belong to the section it is listed under: if nothing in it\n"
        "  fits, use empty items [].\n\n"
        + _examples_block(list(unused), template) +
        f"Sections:\n{blocks}\n"
    )


def complete_coverage(note, transcript_text, normalized_en, verified, llm: LLMClient,
                      timeout=None, parts=None, template: NoteTemplate = DISCHARGE):
    """Check coverage; ask gpt-4.1 once for every dictated part left out.

    The reply runs the same gate and canonicalize as the main note and lands
    only in the sections that had unused parts; text a section already holds
    is not added twice. What is still left out stays in ``coverage.unused``.
    A failed call is recorded, never raised.
    """
    note = check_coverage(note, transcript_text, parts, template)
    unused = note["provenance"]["coverage"]["unused"]
    if not unused:
        return note
    retry = {"sections": list(unused), "parts": sum(len(v) for v in unused.values())}
    try:
        ok, reason = llm.available()
        if not ok:
            raise LLMUnavailable(reason)
        out = llm.complete_json(
            _coverage_prompt(unused, transcript_text, template),
            timeout=timeout or C1.llm.discharge_timeout_s,
            max_tokens=C1.llm.discharge_max_tokens, stage="discharge_coverage")
        json_str = extract_json_object(out)
        reply = json.loads(json_str) if json_str else None
        if not isinstance(reply, dict):
            raise ValueError("no JSON object in the coverage reply")
        gated = gate_discharge({"sections": _parse_sections(reply, keys=list(unused), template=template)},
                               transcript_text, normalized_en, verified, template)
        locked = canonicalize_discharge(gated, verified, template)
    except (LLMError, ValueError, LookupError) as exc:
        retry["error"] = f"{type(exc).__name__}: {exc}"[:200]
        note["provenance"]["coverage"]["retry"] = retry
        return note
    sections = {k: {"items": list((note["sections"].get(k, {}) or {}).get("items", []))}
                for k in template.keys}
    added = 0
    for k in unused:
        have = {str(it.get("text", "")).strip().lower() for it in sections[k]["items"]}
        for it in locked["sections"][k]["items"]:
            key = str(it.get("text", "")).strip().lower()
            if key and key not in have:
                sections[k]["items"].append(it)
                have.add(key)
                added += 1
    retry["added"] = added
    retry["dropped"] = locked["provenance"].get("dropped_unproven", 0)
    prov = dict(note["provenance"])
    prov["coverage"] = {**prov["coverage"], "retry": retry}
    return check_coverage({"sections": _drop_restatements(sections), "provenance": prov},
                          transcript_text, parts, template)
