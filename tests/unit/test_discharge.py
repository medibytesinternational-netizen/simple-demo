"""6-section discharge: prompt map + deterministic pre-fill + gate interplay.

No LLM server needed: prompt/merge/gate are pure functions of transcript +
verified facts. The live-Ollama shape is covered by the manual clip run.
"""
import copy
import json
import re

import pytest
from jsonschema import Draft7Validator, ValidationError

from medibytes.errors import LLMCallFailed
from medibytes.llm.discharge import (
    DISCHARGE_SECTIONS,
    SECTION_EXAMPLES,
    SMALL_TALK_EXAMPLE,
    TRIM_RULE,
    _coverage_prompt,
    _discharge_prompt,
    _fact_index,
    _left_out,
    _prefill_text,
    analyse_transcript,
    canonicalize_discharge,
    check_coverage,
    complete_coverage,
    gate_discharge,
    merge_discharge,
    stamp_schema,
    validate_discharge,
)

TEXT = "Patient has fever. Pulse 92. Give paracetamol 500 mg twice daily. No penicillin allergy."
NORM = TEXT


def _verified():
    return {"facts": [
        {"kind": "symptom", "text": "fever", "status": "verified", "confidence": 0.9,
         "source_sentence": "Patient has fever."},
        {"kind": "vital", "text": "pulse 92", "status": "verified", "confidence": 0.87,
         "source_sentence": "Pulse 92."},
        {"kind": "drug", "name": "paracetamol", "dose": 500.0, "unit": "mg",
         "negated": False, "status": "verified", "confidence": 0.96,
         "source_sentence": "Give paracetamol 500 mg twice daily."},
        {"kind": "allergy", "text": "penicillin", "negated": True, "status": "verified",
         "confidence": 0.82, "source_sentence": "No penicillin allergy."},
    ], "summary": {}}


def _empty():
    return {"sections": {k: {"items": []} for k in DISCHARGE_SECTIONS}, "provenance": {}}


def test_prompt_states_section_map_and_full_proof():
    prompt = _discharge_prompt(TEXT, NORM, _verified(), [])
    for section in ("present_illness", "examination_findings", "plan_of_management"):
        assert section in prompt
    assert "Patient has fever." in prompt  # full proof, never truncated
    assert "seg=" in prompt


def test_prefill_covers_gated_empty_sections_with_tags():
    gated = gate_discharge(_empty(), TEXT, NORM, _verified())
    merged = merge_discharge(_verified(), gated, TEXT, NORM)
    plan = merged["sections"]["plan_of_management"]["items"]
    assert any(i["text"] == "paracetamol 500 mg" and i["verified_kind"] == "drug" for i in plan), plan
    exam = merged["sections"]["examination_findings"]["items"]
    assert any(i["text"] == "pulse 92" for i in exam), exam
    assert merged["provenance"]["prefilled"] >= 3
    assert all(i["confidence"] <= 0.88 for sec in merged["sections"].values() for i in sec["items"])


def test_prefill_never_adds_rejected_or_diet():
    verified = {"facts": [
        {"kind": "drug", "name": "Space", "dose": None, "unit": None, "negated": False,
         "status": "rejected", "confidence": 0.7, "source_sentence": "space today"},
    ], "summary": {}}
    merged = merge_discharge(verified, gate_discharge(_empty(), "space today", "space today", verified),
                             "space today", "space today")
    assert all(sec["items"] == [] for sec in merged["sections"].values())
    assert merged["sections"]["diet_instructions"]["items"] == []


def test_golden_tagged_discharge_validates():
    from medibytes.llm.discharge import _discharge_schema

    schema = _discharge_schema()
    Draft7Validator.check_schema(schema)
    verified = _verified()
    gated = gate_discharge(_empty(), TEXT, NORM, verified)
    merged = merge_discharge(verified, gated, TEXT, NORM)
    stamped = stamp_schema(merged)
    ok, errors = validate_discharge(stamped)
    assert ok, errors
    assert stamped["provenance"]["schema"] == "valid"
    from medibytes.config import SCHEMAS_DIR
    assert (SCHEMAS_DIR / "discharge.schema.json").is_file()


def test_schema_rejects_missing_sentence_extra_section_bad_seg():
    from medibytes.llm.discharge import _discharge_schema

    schema = _discharge_schema()
    verified = _verified()
    gated = gate_discharge(_empty(), TEXT, NORM, verified)
    good = stamp_schema(merge_discharge(verified, gated, TEXT, NORM))

    bad_keys = copy.deepcopy(good)
    del bad_keys["sections"]["diet_instructions"]
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(bad_keys)

    bad_item = copy.deepcopy(good)
    bad_item["sections"]["plan_of_management"]["items"].append({"text": "x"})
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(bad_item)

    bad_seg = copy.deepcopy(good)
    bad_seg["sections"]["present_illness"]["items"].append(
        {"text": "fever", "source_sentence": TEXT, "seg_id": "zero"})
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(bad_seg)

    bad_tag = copy.deepcopy(good)
    bad_tag["sections"]["present_illness"]["items"].append(
        {"text": "fever", "source_sentence": TEXT, "verified_status": "maybe"})
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(bad_tag)


def test_stamp_flags_invalid_but_ships():
    broken = {"sections": {"present_illness": {"items": []}}, "provenance": {}}
    stamped = stamp_schema(broken)
    assert stamped["provenance"]["schema"] == "INVALID"
    assert "present_illness" in stamped["sections"]  # content preserved
    ok, errors = validate_discharge(stamped)
    assert not ok and errors


def test_review_rows_flags_invalid_schema():
    from medibytes.output import review_rows

    ents = {"drugs": [], "vitals": [], "allergies": [],
            "discharge": {"sections": {}, "provenance": {
                "schema": "INVALID", "schema_error": "sections: missing" }}}
    rows = list(review_rows(ents))
    assert ("discharge", "schema INVALID", 0.70, "RED", "sections: missing") in rows


def test_prefill_dedups_llm_items():
    llm = _empty()
    llm["sections"]["plan_of_management"]["items"] = [
        {"text": "paracetamol 500 mg", "source_sentence": "Give paracetamol 500 mg twice daily.",
         "seg_id": 0, "confidence": 0.88}]
    merged = merge_discharge(_verified(), gate_discharge(llm, TEXT, NORM, _verified()), TEXT, NORM)
    plan = merged["sections"]["plan_of_management"]["items"]
    assert len(plan) == 1, plan


# ---- dedup is by fact identity, not by shared proof sentence ----

VITALS_SENT = "His blood pressure is 130/85, pulse is around 92 beats per minute, and respiratory rate is 22."
RX_SENT = "He has been advised paracetamol 650 mg and the doctor also considered amoxicillin."


def _empty_note():
    return {"sections": {k: {"items": []} for k in DISCHARGE_SECTIONS}, "provenance": {}}


def _vfact(text):
    return {"kind": "vital", "text": text, "status": "verified", "confidence": 0.87,
            "source_sentence": VITALS_SENT}


def _items(merged, section):
    return [it["text"] for it in merged["sections"][section]["items"]]


def test_three_vitals_in_one_sentence_all_reach_the_note():
    verified = {"facts": [_vfact("blood pressure is 130/85"), _vfact("pulse is around 92"),
                          _vfact("respiratory rate is 22")]}
    merged = merge_discharge(verified, _empty_note(), VITALS_SENT, VITALS_SENT)
    assert _items(merged, "examination_findings") == [
        "blood pressure is 130/85", "pulse is around 92", "respiratory rate is 22"]


def test_an_llm_item_merging_vitals_does_not_hide_the_others():
    note = _empty_note()
    note["sections"]["examination_findings"]["items"].append(
        {"text": "BP 130/85, pulse 92", "source_sentence": VITALS_SENT})
    verified = {"facts": [_vfact("blood pressure is 130/85"), _vfact("pulse is around 92")]}
    texts = _items(merge_discharge(verified, note, VITALS_SENT, VITALS_SENT), "examination_findings")
    assert "blood pressure is 130/85" in texts and "pulse is around 92" in texts


def test_two_drugs_in_one_sentence_both_reach_the_plan():
    verified = {"facts": [
        {"kind": "drug", "name": "paracetamol", "dose": 650, "unit": "mg", "status": "verified",
         "confidence": 0.96, "source_sentence": RX_SENT},
        {"kind": "drug", "name": "amoxicillin", "dose": None, "unit": None,
         "status": "needs_review", "confidence": 0.7, "source_sentence": RX_SENT}]}
    texts = _items(merge_discharge(verified, _empty_note(), RX_SENT, RX_SENT), "plan_of_management")
    assert texts == ["paracetamol 650 mg", "amoxicillin no dose"]


def test_one_symptom_heard_in_two_sentences_surfaces_once():
    text = "He has fever and cough. For the fever, give paracetamol 650 mg."
    verified = {"facts": [
        {"kind": "symptom", "text": "fever", "status": "verified", "source_sentence": "He has fever and cough."},
        {"kind": "symptom", "text": "fever", "status": "verified",
         "source_sentence": "For the fever, give paracetamol 650 mg."}]}
    assert _items(merge_discharge(verified, _empty_note(), text, text), "present_illness") == ["fever"]


def test_an_llm_item_already_stating_the_drug_suppresses_the_prefill():
    note = _empty_note()
    note["sections"]["plan_of_management"]["items"].append(
        {"text": "Paracetamol 650 mg twice daily", "source_sentence": RX_SENT})
    verified = {"facts": [{"kind": "drug", "name": "paracetamol", "dose": 650, "unit": "mg",
                           "status": "verified", "confidence": 0.96, "source_sentence": RX_SENT}]}
    assert len(_items(merge_discharge(verified, note, RX_SENT, RX_SENT), "plan_of_management")) == 1


def test_a_not_given_item_does_not_cover_an_active_order():
    note = _empty_note()
    note["sections"]["plan_of_management"]["items"].append(
        {"text": "NOT GIVEN: paracetamol 650 mg", "source_sentence": RX_SENT})
    verified = {"facts": [{"kind": "drug", "name": "paracetamol", "dose": 650, "unit": "mg",
                           "status": "verified", "confidence": 0.96, "source_sentence": RX_SENT}]}
    assert len(_items(merge_discharge(verified, note, RX_SENT, RX_SENT), "plan_of_management")) == 2


# ---- fact ids: the model names the fact; canonicalize trusts it only with the right proof ----



def _three_vitals():
    return {"facts": [_vfact("blood pressure is 130/85"), _vfact("pulse is around 92"),
                      _vfact("respiratory rate is 22")]}


def _llm_note(*items, section="examination_findings"):
    note = _empty_note()
    note["sections"][section]["items"] = [dict(i) for i in items]
    return note


def test_prompt_numbers_every_shown_fact_and_skips_rejected():
    verified = _three_vitals()
    verified["facts"].insert(0, {"kind": "drug", "name": "space", "status": "rejected",
                                 "source_sentence": "x"})
    assert [fid for fid, _ in _fact_index(verified)] == ["F1", "F2", "F3"]
    prompt = _discharge_prompt(VITALS_SENT, VITALS_SENT, verified, [])
    assert "- F2 vital -> examination_findings: pulse is around 92" in prompt
    assert "space" not in prompt


def test_fact_id_resolves_one_of_three_vitals_in_a_shared_sentence():
    note = _llm_note({"fact_id": "F2", "text": "Pulse 92 bpm", "source_sentence": VITALS_SENT})
    out = canonicalize_discharge(note, _three_vitals())
    assert _items(out, "examination_findings") == ["pulse is around 92"]


def test_without_a_fact_id_the_numbers_pick_the_vital():
    note = _llm_note({"text": "RR 22", "source_sentence": VITALS_SENT})
    out = canonicalize_discharge(note, _three_vitals())
    assert _items(out, "examination_findings") == ["respiratory rate is 22"]


def test_a_fact_id_with_the_wrong_proof_sentence_is_not_trusted():
    note = _llm_note({"fact_id": "F2", "text": "pulse 92", "source_sentence": "Some other sentence."})
    out = canonicalize_discharge(note, _three_vitals())
    assert _items(out, "examination_findings") == []
    assert out["provenance"]["dropped_unproven"] == 1


def test_a_verified_fact_placed_in_the_wrong_section_moves_home():
    note = _llm_note({"fact_id": "F1", "text": "BP 130/85", "source_sentence": VITALS_SENT},
                     section="general_instructions")
    out = canonicalize_discharge(note, _three_vitals())
    assert _items(out, "general_instructions") == []
    assert _items(out, "examination_findings") == ["blood pressure is 130/85"]


# ---- LLM-only items survive only when purely extractive ----

COMPLAINT = "The cough is productive and he is also complaining about some chest discomfort and shortness of breath."
HISTORY = "He already has a history of hypertension and type two diabetes mellitus."
DENIAL = "There is no history of asthma or chest discomfort."


def _canon_one(text, sentence, section):
    note = _llm_note({"text": text, "source_sentence": sentence}, section=section)
    out = canonicalize_discharge(note, {"facts": []})
    return _items(out, section), out


def test_heard_symptom_with_verbatim_proof_is_kept_and_capped():
    items, out = _canon_one("chest discomfort", COMPLAINT, "present_illness")
    assert items == ["chest discomfort"]
    kept = out["sections"]["present_illness"]["items"][0]
    assert kept["confidence"] <= 0.80 and "llm-extractive" in kept["note"]
    assert out["provenance"]["llm_extractive"] == 1


def test_heard_history_is_kept_in_previous_diagnosis():
    assert _canon_one("hypertension", HISTORY, "previous_diagnosis")[0] == ["hypertension"]


def test_negated_sentence_never_yields_an_extractive_item():
    assert _canon_one("asthma", DENIAL, "previous_diagnosis")[0] == []
    assert _canon_one("chest discomfort", DENIAL, "present_illness")[0] == []


def test_paraphrase_is_not_extractive():
    # "fatigue" was never said; "tired" was.
    assert _canon_one("fatigue", "He says he has been feeling pretty tired.", "present_illness")[0] == []


def test_numbers_and_drugs_need_a_verified_fact():
    assert _canon_one("temperature 101", "His temperature is 101.", "present_illness")[0] == []
    assert _canon_one("paracetamol", "He takes paracetamol for pain.", "general_instructions")[0] == []


# ---- negation scoped to the item, not the whole sentence ----

# A run-on instruction as MedASR heard it: glued "useYour", a "not" at the end.
GEN = ("Lastly, for general instruction, check the aquity index before the exercising outdose "
       "useYour inhaler 15 minutes before or cut on at to urgent care if your breathing does "
       "not does not improve with your rescue me.")


def test_a_late_not_does_not_deny_the_instructions_before_it():
    for text in ("check the aquity index before the exercising",
                 "use your inhaler 15 minutes before"):
        assert _canon_one(text, GEN, "general_instructions")[0] == [text]


def test_a_word_never_said_is_still_refused():
    # "go" was heard as "cut on at to": a guess, not the speaker's word.
    text = "go to urgent care if your breathing does not improve with your rescue"
    assert _canon_one(text, GEN, "general_instructions")[0] == []


def test_an_item_carrying_its_own_not_keeps_its_meaning():
    sent = "Call the office if your breathing does not improve."
    text = "call the office if your breathing does not improve"
    assert _canon_one(text, sent, "general_instructions")[0] == [text]
    assert _canon_one("call the office if your breathing does improve", sent,
                      "general_instructions")[0] == []


def test_denials_are_still_refused():
    assert _canon_one("chest discomfort", DENIAL, "present_illness")[0] == []
    assert _canon_one("fever", "No fever, avoid mosquitoes.", "present_illness")[0] == []
    assert _canon_one("antibiotics", "We will not start antibiotics.", "plan_of_management")[0] == []


def test_a_fragment_proof_cannot_hide_its_denial():
    note = _llm_note({"text": "chest discomfort", "source_sentence": "chest discomfort"},
                     section="present_illness")
    gated = gate_discharge(note, DENIAL, DENIAL, {"facts": []})
    out = canonicalize_discharge(gated, {"facts": []})
    assert _items(out, "present_illness") == []


def test_the_gate_context_never_reaches_the_note():
    gated =gate_discharge(_llm_note({"text": "chest discomfort", "source_sentence": COMPLAINT},
                                     section="present_illness"), COMPLAINT, COMPLAINT, {"facts": []})
    kept = canonicalize_discharge(gated, {"facts": []})["sections"]["present_illness"]["items"]
    assert kept and all("context" not in it for it in kept)


def test_the_plan_never_takes_a_number():
    assert _canon_one("inhaler 15 minutes before", GEN, "plan_of_management")[0] == []


def test_present_illness_takes_a_duration_but_not_a_reading():
    sent = "She has had a dry cough over the last 10 days."
    assert _canon_one("dry cough over the last 10 days", sent, "present_illness")[0] == [
        "dry cough over the last 10 days"]
    assert _canon_one("temperature 101", "His temperature is 101.", "present_illness")[0] == []


# ---- exam findings and symptoms that share a sentence with a verified fact ----

EXAM = ("When I listened to your lung just now I did hear some mild end-expiratory wheezing on "
        "both side through your oxygen level drop great at 98% on room air.")
SYMPTOM = ("You came in today because you have beenu present dry cough and some tightness in "
           "her icest, especially when you jogged in the morning over the last 10 days.")


def test_an_exam_finding_beside_a_vital_is_its_own_item():
    verified = {"facts": [{"kind": "vital", "text": "98% on room air", "status": "verified",
                           "confidence": 0.87, "source_sentence": EXAM}]}
    note = _llm_note({"text": "mild end-expiratory wheezing on both side", "source_sentence": EXAM},
                     {"text": "98% on room air", "source_sentence": EXAM})
    out = canonicalize_discharge(note, verified)
    items = out["sections"]["examination_findings"]["items"]
    assert [i["text"] for i in items] == ["mild end-expiratory wheezing on both side",
                                          "98% on room air"]
    assert items[0]["verified_status"] == "needs_review" and items[0]["confidence"] <= 0.70
    assert items[1]["verified_kind"] == "vital"


def test_a_second_symptom_is_not_rewritten_into_the_verified_one():
    verified = {"facts": [{"kind": "symptom", "text": "cough", "status": "verified",
                           "confidence": 0.9, "source_sentence": SYMPTOM}]}
    note = _llm_note({"text": "dry cough", "source_sentence": SYMPTOM},
                     {"text": "tightness in her icest over the last 10 days", "source_sentence": SYMPTOM},
                     section="present_illness")
    out = canonicalize_discharge(note, verified)
    assert _items(out, "present_illness") == ["cough", "tightness in her icest over the last 10 days"]


def test_a_diagnosis_loses_its_leading_connective():
    fact = {"kind": "diagnosis", "text": "of moderate persistent asthma", "status": "verified",
            "confidence": 0.9, "source_sentence": "previous diagnosis of moderate persistent asthma"}
    assert _prefill_text(fact) == "moderate persistent asthma"


# ---- plan and diet lines with no verified fact behind them ----

PLAN = ("We are going to start you on a short course of anti-inflammatories and I am "
        "referring you to physical therapy twice a week to get that pressure off the nove.")
DIET = ("For the dietary section, I to stick to an anti-inflammatory diet, lot of omega-3 "
        "sleve greins and minimal process su to help reduce tissue swelling.")
SYMPTOM_HEARD = ("You came in today because you have beenu present dry cough and some tightness "
                 "in her icest, especially when you jogged in the morning over the last 10 days.")


def test_heard_plan_lines_are_kept_for_review():
    for text in ("short course of anti-inflammatories", "physical therapy twice a week"):
        items, out = _canon_one(text, PLAN, "plan_of_management")
        assert items == [text]
        kept = out["sections"]["plan_of_management"]["items"][0]
        assert kept["confidence"] <= 0.70 and kept["verified_status"] == "needs_review"
        assert "llm-extractive" in kept["note"]


def test_plan_lines_still_refuse_drugs_numbers_paraphrase_and_negation():
    ibuprofen = "We are going to start you on ibuprofen for the pain."
    assert _canon_one("start you on ibuprofen", ibuprofen, "plan_of_management")[0] == []
    assert _canon_one("paracetamol 500", "Take paracetamol 500 at night.", "plan_of_management")[0] == []
    assert _canon_one("referral to physiotherapy", PLAN, "plan_of_management")[0] == []
    assert _canon_one("antibiotics", "We will not start antibiotics.", "plan_of_management")[0] == []


def test_diet_keeps_a_number_the_sentence_says():
    assert _canon_one("omega-3", DIET, "diet_instructions")[0] == ["omega-3"]
    assert _canon_one("omega-3", "Eat more oily fish.", "diet_instructions")[0] == []


def test_exact_diet_line_keeps_the_usual_cap_and_no_review_flag():
    _, out = _canon_one("anti-inflammatory diet", DIET, "diet_instructions")
    kept = out["sections"]["diet_instructions"]["items"][0]
    assert kept["confidence"] == 0.80 and "llm-corrected" not in kept["note"]
    assert "verified_status" not in kept


def test_diet_accepts_a_small_spelling_fix_held_lower():
    items, out = _canon_one("greens", DIET, "diet_instructions")
    assert items == ["greens"]
    kept = out["sections"]["diet_instructions"]["items"][0]
    assert kept["confidence"] <= 0.70 and "llm-corrected" in kept["note"]
    assert kept["verified_status"] == "needs_review"


def test_diet_refuses_a_word_that_was_not_nearly_heard():
    # "leafy" vs "sleve" is 0.40 similar - a guess, not a spelling fix.
    assert _canon_one("leafy greens", DIET, "diet_instructions")[0] == []


def test_a_spelling_fix_never_becomes_a_medicine():
    # "paracetamal" is one letter off "paracetamol": still a medicine, still refused.
    assert _canon_one("paracetamol", "Take paracetamal with food.", "diet_instructions")[0] == []


def test_the_plan_never_accepts_a_spelling_fix():
    assert _canon_one("greens", DIET, "plan_of_management")[0] == []


def test_a_misheard_symptom_word_may_be_fixed_and_is_held_for_review():
    # MedASR heard "chest" as "icest" (0.80 similar).
    items, out = _canon_one("tightness in her chest over the last 10 days", SYMPTOM_HEARD,
                            "present_illness")
    assert items == ["tightness in her chest over the last 10 days"]
    kept = out["sections"]["present_illness"]["items"][0]
    assert kept["verified_status"] == "needs_review" and "llm-corrected" in kept["note"]


def test_prompt_invites_plan_items_and_verbatim_copy():
    prompt = _discharge_prompt(TEXT, NORM, _verified(), [])
    assert "referrals, therapy, tests or a medicine class" in prompt
    assert "copied exactly as it appears in the transcript, even if misspelled" in prompt


def test_prompt_shows_one_example_item_per_section():
    prompt = _discharge_prompt(TEXT, NORM, _verified(), [])
    assert "never copy its content" in prompt
    for key, (sentence, item) in SECTION_EXAMPLES.items():
        assert f'- {key}: "{item}"\n    heard as: "{sentence}"\n    left out: ' in prompt


def test_examples_extract_and_never_paraphrase():
    # The example must model what canonicalize accepts: every item word was said.
    for key, (sentence, item) in SECTION_EXAMPLES.items():
        heard = set(re.findall(r"[a-z][a-z'-]*", sentence.lower()))
        said = set(re.findall(r"[a-z][a-z'-]*", item.lower()))
        assert said <= heard, (key, said - heard)


def test_examples_trim_the_sentence_to_the_fact():
    words = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")
    for key, (sentence, item) in SECTION_EXAMPLES.items():
        assert len(words.findall(item)) <= 0.7 * len(words.findall(sentence)), key


def test_left_out_lists_the_dropped_words_in_spoken_order():
    sentence, item = SECTION_EXAMPLES["plan_of_management"]
    assert _left_out(sentence, item) == [
        "So the plan is we are going to go ahead and", "her", "and I would like to", "her"]


def test_both_prompts_carry_the_trim_rule_and_the_no_item_example():
    main = _discharge_prompt(TEXT, NORM, _verified(), [])
    retry = _coverage_prompt({"diet_instructions": ["anti-inflammatory diet"]}, DIET)
    for prompt in (main, retry):
        assert TRIM_RULE in prompt
        assert f'no item: heard as: "{SMALL_TALK_EXAMPLE}"' in prompt
        assert "left out: " in prompt
    assert "plan_of_management:" not in retry.split("Sections:")[0]  # only the missing ones


def test_a_copied_example_never_reaches_the_note():
    sentence, item = SECTION_EXAMPLES["plan_of_management"]
    note = _llm_note({"text": item, "source_sentence": sentence}, section="plan_of_management")
    assert _items(gate_discharge(note, TEXT, NORM, _verified()), "plan_of_management") == []


# ---- analysis pass: gpt-4.1 lists the dictated parts ----

T = f"{PLAN} {DIET} {GEN}"


class _StubLLM:
    model = "gpt-4.1"

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def available(self):
        return True, ""

    def complete_json(self, prompt, *, timeout, max_tokens, stage):
        self.calls.append((stage, prompt))
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


def test_analysis_keeps_only_verbatim_quotes_in_known_sections():
    llm = _StubLLM({"parts": [
        {"quote": "short course of anti-inflammatories", "section": "plan_of_management"},
        {"quote": "short course of ibuprofen", "section": "plan_of_management"},   # not said
        {"quote": "physical therapy twice a week", "section": "referrals"},        # no such section
        {"quote": "short course of anti-inflammatories", "section": "plan_of_management"},
        "junk"]})
    parts = analyse_transcript(T, llm)
    assert parts == [{"quote": "short course of anti-inflammatories", "section": "plan_of_management"}]
    assert [stage for stage, _ in llm.calls] == ["discharge_analyse"]


def test_an_unusable_analysis_reply_raises_for_the_cue_fallback():
    with pytest.raises(ValueError):
        analyse_transcript(T, _StubLLM("no json here"))


def test_the_parts_checklist_reaches_the_note_prompt():
    parts = [{"quote": "check the aquity index before the exercising", "section": "general_instructions"}]
    prompt = _discharge_prompt(T, T, _verified(), [], parts)
    assert 'DICTATED PARTS' in prompt
    assert '- general_instructions: "check the aquity index before the exercising"' in prompt
    assert "DICTATED PARTS" not in _discharge_prompt(T, T, _verified(), [])


# ---- coverage: every dictated part reaches the note ----

PARTS = [
    {"quote": "short course of anti-inflammatories", "section": "plan_of_management"},
    {"quote": "physical therapy twice a week", "section": "plan_of_management"},
    {"quote": "anti-inflammatory diet", "section": "diet_instructions"},
    {"quote": "check the aquity index before the exercising", "section": "general_instructions"},
]


def _note_from(**sections):
    note = _empty_note()
    for key, rows in sections.items():
        note["sections"][key]["items"] = [{"text": t, "source_sentence": s} for t, s in rows]
    return note


def test_coverage_lists_every_dictated_part_left_out():
    note = _note_from(plan_of_management=[("short course of anti-inflammatories", PLAN)])
    cov = check_coverage(note, T, PARTS)["provenance"]["coverage"]
    assert cov["source"] == "analysis"
    assert cov["unused"] == {
        "plan_of_management": ["physical therapy twice a week"],  # same sentence, other fact
        "diet_instructions": ["anti-inflammatory diet"],
        "general_instructions": ["check the aquity index before the exercising"]}
    assert cov["missing"] == ["diet_instructions", "general_instructions"]
    assert cov["dictated"]["plan_of_management"] == 2


def test_a_part_written_in_another_section_still_counts():
    note = _note_from(general_instructions=[("anti-inflammatory diet", DIET)])
    cov = check_coverage(note, T, PARTS[2:3])["provenance"]["coverage"]
    assert cov["unused"] == {} and cov["missing"] == ["diet_instructions"]


def test_without_analysis_the_cues_still_find_a_late_negated_instruction():
    cov = check_coverage(_empty_note(), GEN)["provenance"]["coverage"]
    assert cov["source"] == "cues" and "general_instructions" in cov["missing"]


def test_a_denied_topic_does_not_demand_a_section():
    cov = check_coverage(_empty_note(), "No dietary restrictions.")["provenance"]["coverage"]
    assert cov["missing"] == [] and cov["unused"] == {}


def test_retry_asks_once_for_the_unused_parts_and_gates_the_reply():
    llm = _StubLLM({
        "plan_of_management": {"items": [
            {"text": "physical therapy twice a week", "source_sentence": PLAN},
            {"text": "short course of anti-inflammatories", "source_sentence": PLAN},  # already there
            {"text": "ibuprofen", "source_sentence": "We will start ibuprofen."}]},     # not said
        "diet_instructions": {"items": [{"text": "anti-inflammatory diet", "source_sentence": DIET}]},
        "general_instructions": {"items": [
            {"text": "check the aquity index before the exercising", "source_sentence": GEN}]},
        "examination_findings": {"items": [{"text": "wheeze", "source_sentence": GEN}]}})
    note = _note_from(plan_of_management=[("short course of anti-inflammatories", PLAN)])
    out = complete_coverage(note, T, T, {"facts": []}, llm, parts=PARTS)
    [(stage, prompt)] = llm.calls
    assert stage == "discharge_coverage"
    assert 'part: "physical therapy twice a week"' in prompt and f"<<{PLAN}>>" in prompt
    assert _items(out, "plan_of_management") == ["short course of anti-inflammatories",
                                                 "physical therapy twice a week"]
    assert _items(out, "diet_instructions") == ["anti-inflammatory diet"]
    assert _items(out, "general_instructions") == ["check the aquity index before the exercising"]
    assert _items(out, "examination_findings") == []  # no unused exam part: not asked for
    cov = out["provenance"]["coverage"]
    assert cov["unused"] == {} and cov["missing"] == []
    assert cov["retry"]["added"] == 3 and cov["retry"]["dropped"] == 1


def test_retry_is_skipped_when_every_part_is_used():
    llm = _StubLLM({})
    note = _note_from(plan_of_management=[("short course of anti-inflammatories", PLAN)])
    out = complete_coverage(note, T, T, {"facts": []}, llm, parts=PARTS[:1])
    assert llm.calls == [] and "retry" not in out["provenance"]["coverage"]


def test_a_failed_retry_is_recorded_and_the_parts_stay_unused():
    class Broken(_StubLLM):
        def complete_json(self, prompt, **kw):
            raise LLMCallFailed("HTTP 500")
    out = complete_coverage(_empty_note(), T, T, {"facts": []}, Broken({}), parts=PARTS[2:3])
    cov = out["provenance"]["coverage"]
    assert cov["missing"] == ["diet_instructions"] and "LLMCallFailed" in cov["retry"]["error"]


def test_one_shared_word_does_not_cover_a_long_part():
    part = {"quote": "dry cough and some tightness in her icest", "section": "present_illness"}
    only_cough = _note_from(present_illness=[("cough", SYMPTOM_HEARD)])
    both = _note_from(present_illness=[("cough", SYMPTOM_HEARD),
                                       ("tightness in her chest", SYMPTOM_HEARD)])
    assert check_coverage(only_cough, SYMPTOM_HEARD, [part])["provenance"]["coverage"]["unused"]
    assert not check_coverage(both, SYMPTOM_HEARD, [part])["provenance"]["coverage"]["unused"]


def test_a_line_restating_another_is_dropped_but_one_adding_detail_stays():
    sent = "This is a flare-up of your previous diagnosis of moderate persistent asthma."
    verified = {"facts": [{"kind": "diagnosis", "text": "of moderate persistent asthma",
                           "status": "verified", "confidence": 0.9,
                           "source_sentence": "diagnosis of moderate persistent asthma"}]}
    note = _llm_note({"text": "previous diagnosis of moderate persistent asthma", "source_sentence": sent},
                     {"text": "flare-up of moderate persistent asthma", "source_sentence": sent},
                     section="previous_diagnosis")
    locked = canonicalize_discharge(note, verified)
    merged = merge_discharge(verified, locked, sent, sent)
    # The restatement is gone; the line with the extra word stays and already
    # states the verified diagnosis, so merge does not add it a second time.
    assert _items(merged, "previous_diagnosis") == ["flare-up of moderate persistent asthma"]


def test_a_detailed_symptom_line_beside_its_verified_fact_keeps_the_detail():
    verified = {"facts": [{"kind": "symptom", "text": "cough", "status": "verified",
                           "confidence": 0.9, "source_sentence": SYMPTOM_HEARD}]}
    text = "dry cough and some tightness in her chest over the last 10 days"
    note = _llm_note({"text": "cough", "source_sentence": SYMPTOM_HEARD, "fact_id": "F1"},
                     {"text": text, "source_sentence": SYMPTOM_HEARD}, section="present_illness")
    out = canonicalize_discharge(note, verified)
    assert _items(out, "present_illness") == ["cough", text]


def test_a_dose_line_beside_its_verified_drug_is_never_kept_as_detail():
    out = canonicalize_discharge(_llm_note(
        {"text": "paracetamol 500 mg twice daily for fever", "source_sentence": TEXT.split(". ")[2] + "."},
        section="plan_of_management"), _verified())
    assert _items(out, "plan_of_management") == ["paracetamol 500 mg"]


def test_a_reading_part_is_covered_by_its_numbers():
    part = {"quote": "oxygen level drop great at 98% on room air", "section": "examination_findings"}
    note = _note_from(examination_findings=[("98% on room air", EXAM)])
    assert check_coverage(note, EXAM, [part])["provenance"]["coverage"]["unused"] == {}
