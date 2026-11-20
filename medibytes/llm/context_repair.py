"""Stage 5b - gpt-4.1 context repair of drug names the string matcher gave up on.

The doseless matcher needs a 0.84 spelling score. Between 0.78 and 0.84 the
sentence decides: for each word that could be a misheard medicine this stage
shortlists substances by spelling and asks gpt-4.1 which one - if any - the
sentence is about. Same rules as term validation: closed shortlist, a repaired
row is never better than RED, "none" is a normal answer, failures are recorded.
"""
from __future__ import annotations

import json
import re
import time

from ..config import C1
from ..errors import LLMUnavailable
from ..ports import LLMClient
from ..reference import drug_reference
from ..reference.english import is_ordinary_word
from .json_reply import extract_json_object

# Spelling floor for a candidate to be *offered*: the reference module's own
# `FUZZY_FLOOR`, the bar a dosed mention already clears. A row built from
# spelling alone still needs `DOSELESS_FUZZY_FLOOR` (0.84); between the two the
# sentence decides. (A first version used 0.70 and let a 3B model approve
# `certain` -> ceritinib and `boosting` -> bosutinib.)
CONTEXT_FLOOR = C1.llm.repair_floor


CONTEXT_BAND = C1.llm.repair_band         # keep candidates within this of the best


MAX_CANDIDATES = C1.llm.repair_limit


MIN_TOKEN_LEN = C1.llm.repair_min_token_len


MIN_CONFIDENCE = C1.llm.repair_min_confidence       # an LLM answer at or under this is a "none"


MAX_CALLS_PER_CLIP = C1.llm.repair_max_calls     # a runaway guard, not a tuning knob


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


_WORD = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*")


# A sentence that is not about a medicine cannot contain a misheard one. Without
# this the stage would shortlist every long English word in a ward handover.
_CUE = re.compile(
    r"\b(?:take|takes|taking|taken|medicine|medication|medications|drug|drugs|tablet|tablets|"
    r"tab|capsule|capsules|syrup|injection|infusion|prescri\w+|contain\w*|regimen|dose|doses|"
    r"dosage|therapy|treatment|given|give|advised|started|receiving|received|used|component|"
    r"antibiotic|supplement|sweetener|ointment|solution|drops)\b", re.I)


def _prompt(token: str, sentence: str, candidates: list[dict]) -> str:
    listing = "\n".join(
        f"- {c['name']} (forms: {', '.join(c.get('forms') or []) or 'n/a'})" for c in candidates)
    return (
        "You are a clinical speech-recognition post-processor. A speech recogniser\n"
        "may have misheard ONE word in this sentence as a non-word. A spelling matcher\n"
        "shortlisted medicines whose names look like that word.\n\n"
        "Decide whether the word is a mishearing of exactly one shortlisted medicine,\n"
        "using what the SENTENCE says about it: what it treats, what it is, how it is\n"
        "given. Spelling similarity alone is not evidence.\n\n"
        "Return STRICT JSON only:\n"
        '{"decision": "candidate" | "none", "chosen": "<name copied from the shortlist, or empty>",\n'
        ' "confidence": 0.0, "reason": "<one short clause>"}\n\n'
        "Rules:\n"
        '- "chosen" must be copied exactly from the shortlist. Never name a medicine that is not listed.\n'
        '- Answer "none" if the word is an ordinary word, a product brand name, or if the\n'
        "  sentence does not clearly point to one shortlisted medicine. A wrong drug on a\n"
        '  chart injures a patient; "none" only costs a clinician a glance.\n'
        "- Two shortlisted medicines that both fit the sentence also means \"none\".\n\n"
        f"Sentence: {sentence[:500]}\n"
        f"Word: {token}\n"
        f"Shortlist:\n{listing}\n")


def _llm_runner(llm: LLMClient, timeout):
    checked: list[bool] = []

    def run(prompt: str) -> dict:
        if not checked:
            ok, reason = llm.available()
            if not ok:
                raise LLMUnavailable(reason)
            checked.append(True)
        raw = extract_json_object(llm.complete_json(
            prompt, timeout=timeout, max_tokens=C1.llm.repair_max_tokens,
            stage="context_repair"))
        if not raw:
            raise ValueError("no JSON in context-repair output")
        return json.loads(raw)

    return run


def eligible_tokens(sentence: str, claimed: set[str], stopwords) -> list[str]:
    """Words worth shortlisting.

    Long, not a stopword, not an ordinary English word, not already an exact
    reference name, and not one half of a multi-word name (`fenofibric` in
    `fenofibric acid`, `etabonate` in `loteprednol etabonate`).
    """
    from ..reference import drug_reference
    found = [(m.group(0), m.group(0).lower()) for m in _WORD.finditer(sentence)]
    in_name: set[int] = set()
    for i in range(len(found)):
        for n in (3, 2):
            if i + n <= len(found) and drug_reference.is_substance_name(
                    " ".join(low for _, low in found[i:i + n])):
                in_name.update(range(i, i + n))
    out, seen = [], set()
    for i, (w, low) in enumerate(found):
        if (i in in_name or len(low) < MIN_TOKEN_LEN or low in stopwords or low in claimed
                or low in seen or is_ordinary_word(low)
                or drug_reference.is_substance_name(low)
                or drug_reference.lookup(low, block=stopwords, brands=False)):
            continue
        seen.add(low)
        out.append(w)
    return out


def judge(token: str, sentence: str, candidates: list[dict], run, prompt=_prompt) -> dict:
    """One verdict. Raises ValueError when the model could not be consulted."""
    closed = {c["name"].lower(): c["name"] for c in candidates}
    verdict = run(prompt(token, sentence, candidates))
    if not isinstance(verdict, dict):
        raise ValueError("context-repair JSON is not an object")
    try:
        conf = min(max(float(verdict.get("confidence", 0.0)), 0.0), 1.0)
    except (TypeError, ValueError):
        conf = 0.0
    reason = str(verdict.get("reason", "") or "")[:160]
    chosen = str(verdict.get("chosen", "") or "").strip()
    if str(verdict.get("decision", "")).strip().lower() != "candidate" or not chosen:
        return {"status": "none", "confidence": conf, "reason": reason}
    if chosen.lower() not in closed:
        raise ValueError(f"model chose {chosen!r}, outside the shortlist")
    if conf < MIN_CONFIDENCE:
        return {"status": "none", "confidence": conf, "reason": reason or f"confidence {conf:.2f}"}
    return {"status": "repaired", "chosen": closed[chosen.lower()], "confidence": conf, "reason": reason}


def apply_context_repair(entities: dict, normalized_text: str, *, chart_name, stopwords,
                         llm: LLMClient | None = None, timeout=C1.llm.repair_timeout_s,
                         runner=None, skip_sentence=None) -> dict:
    """Add RED rows for misheard medicines the LLM can place from context. In place.

    `skip_sentence` lets the caller veto a sentence outright. The extractor passes its
    lab-request test, because "requested cardiac troponin levels" is the one place a
    3B model reliably approves `troponin` -> tiopronin: the sentence names a
    test, not a medicine, and the doseless path already refuses it for that reason.
    """
    version = C1.llm.prompt_version
    settings = {"floor": CONTEXT_FLOOR, "band": CONTEXT_BAND, "limit": MAX_CANDIDATES}
    if llm is None and runner is None:
        raise TypeError("apply_context_repair needs an LLM client or an injected runner")
    if runner is not None:
        run, model = runner, (llm.model if llm is not None else "injected")
    else:
        assert llm is not None
        run, model = _llm_runner(llm, timeout), llm.model
    have = {str(d.get("name", "")).lower() for d in entities.get("drugs", []) if isinstance(d, dict)}
    claimed = {str(d.get("raw_token") or "").lower() for d in entities.get("drugs", [])
               if isinstance(d, dict)}
    log: dict = {"engine": "injected" if runner else f"llm:{model}", "considered": 0, "calls": 0,
                 "llm_seconds": 0.0, "repaired": [], "declined": [], "errors": [],
                 "prompt_version": version, "shortlist_settings": settings, "attempts": []}
    for sentence in _SENT_SPLIT.split(normalized_text or ""):
        if not _CUE.search(sentence) or (skip_sentence and skip_sentence(sentence)):
            continue
        for token in eligible_tokens(sentence, claimed, stopwords):
            cands = drug_reference.candidates(token, floor=settings["floor"],
                                              band=settings["band"], limit=settings["limit"])
            if not cands:
                continue
            log["considered"] += 1
            shortlist: list[dict] = []
            for c in cands:
                shown = chart_name(c["name"])
                if shown.lower() not in {s["name"].lower() for s in shortlist}:
                    shortlist.append({**c, "name": shown})
            if log["calls"] >= MAX_CALLS_PER_CLIP:
                log["errors"].append("call cap reached")
                break
            # Every call, whatever came of it, so an evaluation can tell a shortlist
            # that missed the drug from a model that missed it on the shortlist.
            attempt = {"heard": token, "sentence": sentence.strip()[:500],
                       "shortlist": [(c["name"], c["score"]) for c in shortlist]}
            log["attempts"].append(attempt)
            t0 = time.perf_counter()
            try:
                verdict = judge(token, sentence, shortlist, run)
            except Exception as err:
                attempt["outcome"] = "error"
                log["errors"].append(f"{token}: {type(err).__name__}: {err}"[:160])
                if isinstance(err, LLMUnavailable):
                    entities["context_repair"] = {**log, "status": "skipped", "reason": str(err)[:160]}
                    return entities
                continue
            finally:
                log["calls"] += 1
                log["llm_seconds"] = round(log["llm_seconds"] + time.perf_counter() - t0, 3)
            top = next(c for c in shortlist if c["name"] == verdict.get("chosen")) \
                if verdict["status"] == "repaired" else shortlist[0]
            record = {"heard": token, "shortlist": [(c["name"], c["score"]) for c in shortlist],
                      "confidence": verdict["confidence"], "reason": verdict["reason"]}
            attempt.update(outcome=verdict["status"], chosen=verdict.get("chosen"),
                           confidence=verdict["confidence"])
            if verdict["status"] != "repaired":
                log["declined"].append(record)
                continue
            chosen = verdict["chosen"]
            if chosen.lower() in have:
                attempt["outcome"] = "duplicate"
                continue
            have.add(chosen.lower())
            entities.setdefault("drugs", []).append({
                "name": chosen, "dose": None, "unit": None, "frequency": "", "duration": "",
                "confidence": 0.65, "color": "RED", "negated": False,
                "source_sentence": sentence.strip(),
                "note": (f"context repair {token}->{chosen} (spelling {top['score']:.2f}, "
                         f"LLM {verdict['confidence']:.2f}: {verdict['reason']}) - physician must confirm"),
                "context_repair": {"heard": token, "model": model,
                                   "shortlist": record["shortlist"]},
            })
            log["repaired"].append({**record, "chosen": chosen})
    entities["context_repair"] = {**log, "status": "ran"}
    return entities
