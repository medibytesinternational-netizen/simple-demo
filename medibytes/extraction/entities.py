"""Stage 4 - regex entity extraction with negation and fuzzy drug repair.

Reads a transcript sentence by sentence and returns the chart rows: drugs
(dosed and doseless), symptoms, vitals, allergies, diagnosis and follow-up.
No model is loaded here.
"""
import re

from ..config import C1
from .allergens import ALLERGY_ASSERT, ALLERGY_CTX, ALLERGY_STOPWORDS, allergy_spans, reconcile_allergens
from .drug_matching import (
    combination_partner,
    demote_implausible,
    drug_name_pattern,
    extend_name,
    fuzzy_candidates,
    is_lab_concentration,
    reference_candidates,
    reference_doseless,
    reference_only_row,
)
from .negation import drug_negated, negated_before
from .numerals import numwords_to_digits
from .spans import annotate_entity_spans
from .vitals import VITALS_PAT, vital_span_plausible
from .vocabulary import load_drug_list

SYMPTOMS = ["fever", "cough", "chest pain", "headache", "vomiting", "diarrhea",
            "breathlessness", "sore throat", "cold", "pain", "bukhar", "khansi"]


# "cold drinks" / "cold water" in a diet instruction is not the symptom "cold".
_COLD_DIET = re.compile(r"cold\s+(?:drinks?|water|foods?|beverages?|fluids?|liquids?|items?|diet|meals?)\b")


def _symptom_at(low, symptom):
    """Index of the first mention of `symptom` in lower-cased `low` that is one, else -1."""
    start = 0
    while (at := low.find(symptom, start)) != -1:
        if not (symptom == "cold" and _COLD_DIET.match(low, at)):
            return at
        start = at + 1
    return -1


FREQ_PAT = (r"BID|OD|TDS|QID|once daily|twice daily|thrice daily|daily|B\.I\.D\.?"
            r"|twice a day|two times a day|thrice a day|three times a day"
            r"|every\s+\d+\s*(?:hours?|hrs?|minutes?|mins?)|q\d+h"
            r"|as needed|as\s+required|PRN|S\.?O\.?S\.?|stat|BD|TID")


DRUG_CTX = re.compile(
    r"(?P<name>[A-Za-z]+),?\s+(?:for\s+)?(?P<dose>\d+(?:\.\d+)?)\s*(?P<unit>mg|mcg|g|ml|U|units?|milligrams?|micrograms?|grams?|milliliters?)\b"
    r"(?:\s*(?P<freq>" + FREQ_PAT + r"))?"
    r"(?:[^.]{0,60}?(?P<dur>\d+)\s*(?P<durunit>days?|din\b|weeks?|months?|hours?|hrs?|minutes?|mins?))?",
    re.I,
)


# Split multi-drug sentences: "amox ... along with ibuprofen ..." -> two clauses
DRUG_SPLIT_PAT = re.compile(r"\s+(?:along with|alongwith|plus|and also|\+)\s+", re.I)


UCUM = {"milligram": "mg", "milligrams": "mg", "microgram": "mcg", "micrograms": "mcg",
        "gram": "g", "grams": "g", "milliliter": "ml", "milliliters": "ml",
        "units": "U", "unit": "U"}


SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _prefer_dosed(drugs):
    """One row per drug, and the dosed row wins.

    A drug can be named twice - once bare ("continuing ceftriaxone") and once
    with its dose. Whichever is dictated first, the row carrying the dose is the
    one the record needs, so the bare row is dropped rather than left to shadow
    it.
    """
    best: dict[str, dict] = {}
    for drug in drugs:
        name = drug["name"]
        if name not in best or (best[name].get("dose") is None and drug.get("dose") is not None):
            best[name] = drug
    return list(best.values())


def _overlaps(spans, start, end):
    return any(start < s_end and s_start < end for s_start, s_end in spans)


def _split_clauses(sent):
    """Multi-drug clauses as `(text, offset)`, offset measured in `sent`.

    The offset is what lets a negation keep its reach across the split: "do not
    give amoxicillin along with ibuprofen" denies both drugs, and a clause
    examined on its own would have lost the "not" that governs it.
    """
    out, at = [], 0
    for m in DRUG_SPLIT_PAT.finditer(sent):
        out.append((sent[at:m.start()], at))
        at = m.end()
    out.append((sent[at:], at))
    return out


def extract_entities(text, normalized_en, segments):
    """Stage 4 regex core: chart rows (drugs, symptoms, vitals, allergies, diagnosis,
    follow-up) from one transcript, with negation, fuzzy repair and character spans."""
    drugs_known = {d["name"].lower() for d in load_drug_list()}
    alias_to_canonical = {}
    for d in load_drug_list():
        for a in [d["name"]] + d.get("aliases", []):
            alias_to_canonical[a.lower()] = d["name"].lower()
    known_name_pat = drug_name_pattern(alias_to_canonical)

    drugs: list[dict] = []
    symptoms: list[dict] = []
    vitals: list[dict] = []
    allergies: list[dict] = []
    negations: list[dict] = []
    # cross-sentence join: "paracetamol,\n500 mg" -> "paracetamol 500 mg"
    # also "ibuprofen, for 100 mg" -> "ibuprofen for 100 mg" (second-drug clause)
    text = re.sub(r"([A-Za-z]+),\s+(?=(?:for\s+)?\d+\s*(?:mg|mcg|g|ml|U)\b)", r"\1 ", text)
    sents = SENT_SPLIT.split(text)
    # match on digitized copy, keep original wording as proof
    etext = numwords_to_digits(text)
    esents = SENT_SPLIT.split(etext)
    pairs = list(zip(esents, sents, strict=False)) if len(esents) == len(sents) else [(s, s) for s in sents]
    sents = [p[0] for p in pairs]
    raws = [p[1] for p in pairs]
    diagnosis, followup = {}, {}

    for sent, raw in zip(sents, raws, strict=False):
        proof_sent = raw.strip()
        claimed_spans = allergy_spans(sent)
        # multi-drug split: "amox ... along with ibuprofen ..." -> separate clauses
        # so the second drug's dose/freq is not swallowed by the first row's duration window
        drug_clauses = _split_clauses(sent)
        for clause, clause_at in drug_clauses:
            for m in DRUG_CTX.finditer(clause):
                if is_lab_concentration(clause, m):
                    continue
                rawm, name_at, extended = extend_name(
                    clause, m.start("name"), m.end("name"),
                    drugs_known, alias_to_canonical)
                canon = alias_to_canonical.get(rawm)
                fuzzy_note, candidates = "", []
                ref_hit = None
                if canon is None and rawm not in drugs_known:
                    # An exact hit in the national reference is not a guess, so
                    # it short-circuits the sound-alike path entirely: no
                    # candidates, nothing for the validator to weigh.
                    exact = reference_only_row(rawm, drugs_known)
                    if exact:
                        canon, ref_hit = exact
                        fuzzy_note = ("reference-only: in the national drug "
                                      "list, not in this pipeline's own list")
                    else:
                        # fuzzy sound-alike fallback: asitromaisin -> azithromycin (difflib stand-in)
                        floor = (C1.matcher.dosed_floor_long if len(rawm) >= C1.matcher.dosed_long_len
                                 else C1.matcher.dosed_floor_short)
                        candidates = fuzzy_candidates(rawm, drugs_known, alias_to_canonical, floor)
                        candidates = reference_candidates(rawm, candidates, drugs_known)
                        if candidates:
                            canon, score = candidates[0]["name"], candidates[0]["score"]
                            fuzzy_note = f"fuzzy {rawm}->{canon} ({score:.2f})"
                        else:
                            continue  # skip non-drug words; drug_list is the mini-RxNorm
                if _overlaps(claimed_spans, name_at, m.end("name")):
                    continue  # the allergy rules below own this mention
                dose = float(m.group("dose")) if m.group("dose") else None
                raw_unit = (m.group("unit") or "").strip()
                unit = UCUM.get(raw_unit.lower(), raw_unit) or None  # milligram->mg (UCUM)
                freq = (m.group("freq") or "").strip()
                dur = f"{m.group('dur')} {m.group('durunit')}" if m.group("dur") else ""
                if not dose or not unit:
                    conf, color = 0.70, "RED"  # dose/unit missing -> physician must fix
                else:
                    conf = 0.96
                    color = "GREEN"
                matcher_pick = canon
                dose_red = ""
                if candidates and dose and unit:
                    # The pack's dose check runs here, not only in the
                    # gpt-4.1 validator: a sentence whose dose is impossible
                    # for the matched drug must not depend on an LLM call
                    # succeeding to say so.
                    candidates, ruled_out, all_bad = demote_implausible(
                        candidates, dose, unit)
                    if all_bad:
                        # Every candidate is a drug this dose cannot belong to.
                        # Nothing here is safe to put on a chart.
                        dose_red = (f"dose {('%g' % dose)} {unit} implausible for "
                                    f"every candidate: {', '.join(ruled_out)}")
                    elif ruled_out and candidates[0]["name"] != canon:
                        # The pack overruled the string matcher. Two signals
                        # disagreeing about which drug was said is the
                        # sound-alike hazard itself, and `term_validate`
                        # sends that to a human rather than to a chart.
                        dose_red = (f"{canon} ruled out on dose; pack prefers "
                                    f"{candidates[0]['name']}")
                        canon = candidates[0]["name"]
                    elif ruled_out:
                        fuzzy_note = (f"{fuzzy_note}; dose implausible for "
                                      f"{', '.join(ruled_out)}")
                # "amoxicillin and clavulanic acid 625 mg" is one combination
                # tablet and 625 is its total strength, not this component's
                # dose. Before the multi-word name existed this sentence could
                # not produce a dosed row at all, so the guard is scoped to
                # the newly reachable case rather than rewriting how a dose
                # attaches to a conjoined single-word drug, which is older
                # behaviour nobody asked to change here.
                if extended and dose and not dose_red:
                    partner = combination_partner(
                        clause, name_at, drugs_known, alias_to_canonical)
                    if partner:
                        dose_red = (f"combination order: {dose:g} {unit or ''} may be "
                                    f"the total for {partner} + {canon or rawm} "
                                    "- physician must confirm")
                if fuzzy_note:
                    conf = 0.88  # fuzzy match -> YELLOW, human must glance
                    color = "YELLOW"
                if dose_red:
                    fuzzy_note = f"{fuzzy_note}; {dose_red}".strip("; ")
                    conf, color = 0.70, "RED"
                # A prohibition is not a prescription. The sentence's negation
                # used to gate symptoms only, so "do not give
                # ibuprofen 400 mg" and "stop metformin 500 mg" both charted as
                # active GREEN orders. The doseless path already guards this
                # with `negated_before`; the dosed path simply never did.
                # Scope is the same prefix test, so "she has no fever, give
                # paracetamol 500 mg" still prescribes.
                negated = drug_negated(sent[:clause_at + name_at])
                if negated:
                    # The row leaves the active medication list and is rendered
                    # under NOT GIVEN instead, so a mis-scoped negation is
                    # visible as a wrong entry there rather than as an order
                    # that simply vanished. RED marks it for review either way.
                    conf, color = min(conf, 0.70), "RED"
                drugs.append({"name": canon or rawm, "dose": dose, "unit": unit,
                              "frequency": freq, "duration": dur,
                              "confidence": conf, "color": color,
                              "source_sentence": proof_sent, "negated": negated,
                              **({"note": fuzzy_note} if fuzzy_note else {}),
                              # the validation stage needs the word that was
                              # actually heard and every term it could have been,
                              # not just the one difflib ranked first
                              # the validation stage needs the word that was
                              # actually heard and every term it could have been,
                              # not just the one difflib ranked first. An exact
                              # reference hit has no candidates, so it is not a
                              # flagged row and the validator leaves it alone.
                              **({"raw_token": rawm, "candidates": candidates,
                                  # the string matcher's own pick, recorded
                                  # before the dose check reordered anything,
                                  # so the validator can still tell whether
                                  # the drug on this row is the one the
                                  # matcher proposed
                                  "matcher_pick": matcher_pick}
                                 if fuzzy_note and candidates else {}),
                              **({"reference": {"kind": ref_hit["kind"],
                                                "name": ref_hit["name"],
                                                "substances": ref_hit.get("substances", []),
                                                "units": ref_hit.get("units", []),
                                                "mass_mg": ref_hit.get("mass_mg")}}
                                 if ref_hit else {})})
        # Doseless drugs. `DRUG_CTX` requires name + number + unit, so a drug
        # dictated without one ("he is continuing ceftriaxone", "takes insulin
        # before meals") is invisible even with a perfect transcript. Those are
        # most of what a ward handover says, so a known drug-list name standing
        # on its own is recorded too - RED, because the missing dose is exactly
        # what the existing rule says a physician must fill in.
        for nm in known_name_pat.finditer(sent):
            canon = alias_to_canonical.get(nm.group(0).lower())
            if not canon or any(d["name"] == canon for d in drugs):
                continue
            if _overlaps(claimed_spans, nm.start(), nm.end()):
                continue
            if negated_before(sent[:nm.start()]):
                continue  # "cannot take amoxicillin" is a prohibition, not an order
            drugs.append({"name": canon, "dose": None, "unit": None,
                          "frequency": "", "duration": "",
                          "confidence": 0.70, "color": "RED",
                          "source_sentence": proof_sent, "negated": False,
                          "note": "no dose dictated - physician must confirm"})
        for canon, cstart, cend, heard, fuzzy in reference_doseless(
                sent, {d["name"] for d in drugs}, alias_to_canonical, drugs_known):
            if any(d["name"] == canon for d in drugs):
                continue
            if _overlaps(claimed_spans, cstart, cend):
                continue
            if drug_negated(sent[:cstart]):
                continue
            note = ("no dose dictated - physician must confirm "
                    "(national drug list, not this pipeline's own)")
            row = {"name": canon, "dose": None, "unit": None,
                   "frequency": "", "duration": "",
                   "confidence": 0.70, "color": "RED",
                   "source_sentence": proof_sent, "negated": False}
            if fuzzy:
                # A doseless fuzzy match is the weakest evidence this pipeline
                # produces: a misheard word, no dose to corroborate it, and no
                # curated alias behind it. It carries the heard token and the
                # full candidate list so `term_validate` can weigh it, and it
                # says on the row what it was repaired from.
                note = (f"fuzzy {heard}->{canon} ({fuzzy[0]['score']:.2f}), "
                        f"no dose dictated - physician must confirm")
                row.update(raw_token=heard, candidates=fuzzy, matcher_pick=canon)
            row["note"] = note
            drugs.append(row)
        low = sent.lower()
        matched: set[str] = set()
        for s in SYMPTOMS:
            at = _symptom_at(low, s)
            if at >= 0:
                # skip substring dup: "pain" inside already-matched "chest pain"
                if any(s in m and s != m for m in matched):
                    continue
                matched.add(s)
                # Scoped to what precedes the mention, like allergies and drugs: "denies
                # fever and chest pain" denies both, "cough but no fever" only the fever.
                is_neg = negated_before(sent[:at])
                symptoms.append({"text": s, "confidence": 0.9 if not is_neg else 0.91,
                                 "color": "GREEN" if is_neg else "YELLOW",
                                 "source_sentence": proof_sent,
                                 "negated": is_neg,
                                 **({"note": "DENIED - excluded"} if is_neg else {})})
        # standalone allergy mention without dose, e.g. "No penicillin allergy"
        # legacy allowlist first, then generic "allergy to X" candidate (YELLOW, negated if NEG_PAT)
        # Both word orders - "allergy to X" and "X ... allergy" - and in both the
        # polarity is read from the text BEFORE the substance, never from the
        # sentence. The two are not the same: "document X as a suspected allergy
        # so that it is not given again" is an ASSERTION inside a sentence that
        # trips NEG_PAT, and recording that as a denial is the failure mode that
        # gets a patient re-dosed.
        #
        # `ALLERGY_CTX` keeps its open capture, so an unknown word after
        # "allergy to" is still surfaced for a human to check. `ALLERGY_ASSERT`
        # scans backwards from the word "allergy" and cannot, so it accepts only
        # known drug names - otherwise "patient denies drug allergies" records an
        # allergy to "denies".
        for pattern, known_only in ((ALLERGY_CTX, False), (ALLERGY_ASSERT, True)):
            for am in pattern.finditer(sent):
                cand = (am.group("drug") or "").lower()
                canon = alias_to_canonical.get(cand, cand)
                if not cand or cand in ALLERGY_STOPWORDS:
                    continue
                if known_only and cand not in alias_to_canonical:
                    continue
                if any(a.get("text") == canon for a in allergies):
                    continue
                if negated_before(sent[:am.start("drug")]):
                    allergies.append({"text": canon, "negated": True, "confidence": 0.82,
                                      "color": "YELLOW", "source_sentence": proof_sent,
                                      "note": "NEGATED candidate - verify drug name"})
                    negations.append({"span": proof_sent[:60], "negated": True})
                else:
                    allergies.append({"text": canon, "negated": False, "confidence": 0.82,
                                      "color": "RED", "source_sentence": proof_sent,
                                      "note": "ASSERTED allergy - confirm before prescribing"})
        for vm in VITALS_PAT.finditer(sent):
            ok, note = vital_span_plausible(vm.group(0))
            if ok:
                vitals.append({"text": vm.group(0), "confidence": 0.87, "color": "YELLOW",
                               "source_sentence": proof_sent})
            else:
                vitals.append({"text": vm.group(0), "confidence": 0.70, "color": "RED",
                               "source_sentence": proof_sent, "note": note})
        if re.search(r"\bno allergy\b", sent, re.I):
            negations.append({"span": "No allergy", "negated": True,
                              "note": "rule stand-in for CAN-BERT"})

    # diagnosis + follow-up sentences
    dx = re.search(r"diagnosis\s*[—–\-:]*\s*([^.]+)", text, re.I)
    if dx and dx.group(1).strip():
        diagnosis = {"text": dx.group(1).strip(), "icd10": "", "confidence": 0.85,
                     "color": "YELLOW", "source_sentence": dx.group(0).strip()}
    fu = re.search(r"(review after[^.]+|follow[- ]?up[^.]+|come back[^.]+|in one week[^.]*|in \d+ (?:days?|weeks?)[^.]*follow[^.]*)", text, re.I)
    if fu:
        followup = {"text": fu.group(1).strip(), "confidence": 0.88, "color": "YELLOW",
                    "source_sentence": fu.group(0).strip()}

    drugs = _prefer_dosed(drugs)
    return annotate_entity_spans(
        reconcile_allergens(
            {"drugs": drugs, "symptoms": symptoms, "vitals": vitals,
             "allergies": allergies, "negations": negations,
             "diagnosis": diagnosis, "followup": followup}),
        normalized_en,
    )
