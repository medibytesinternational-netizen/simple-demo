"""The 6-section discharge note: the format the Phone40 C1 score (212/229) was measured on.

These strings are the prompt. Change one only together with a re-score
(`python -m evaluation.phone40.score`).
"""
from __future__ import annotations

from .base import BASE_SECTIONS, NoteTemplate, SectionSpec

# What each section holds; stated in the note prompt and the coverage retry.
SECTION_RULES = {
    "present_illness": "each symptom the patient has, with its duration, one per item "
                       "(prefix DENIED: if marked DENIED)",
    "examination_findings": "vital-sign readings and other examination findings "
                            "(e.g. breath sounds, tenderness, swelling, reflexes)",
    "previous_diagnosis": "past history and diagnosis statements",
    "plan_of_management": "prescribed drugs with dose/unit/frequency PLUS follow-up plans, "
                          'referrals and therapy (prefix "NOT GIVEN: " if marked NOT GIVEN)',
    "diet_instructions": "ONLY diet/food/fluid advice actually spoken, else []",
    "general_instructions": "allergy statements (prefix DENIED if denied) and other spoken advice",
}


# One good item per section: (sentence the doctor said, item written from it).
# A different patient, shown for style only. Each sentence is real dictation -
# filler, the doctor talking to the patient, asides - and its item keeps only
# the words that state the fact, in the order said. Every item word is a word
# of its sentence, so the example teaches trimming, not paraphrase (a
# paraphrased item fails canonicalize). A copied example can never reach a
# note: its sentence is not in the transcript, so the verbatim gate drops it.
SECTION_EXAMPLES = {
    "present_illness": (
        "So she tells me she has been getting this burning chest discomfort and a sour taste, "
        "mostly after meals, for about one month now.",
        "Burning chest discomfort and sour taste after meals for one month."),
    "examination_findings": (
        "When I examined her today the abdomen was soft and non-tender, no distension, "
        "and honestly no acute findings at all.",
        "Abdomen soft and non-tender; no distension; no acute findings."),
    "previous_diagnosis": (
        "And just so you know, she was previously diagnosed with Gastroesophageal Reflux "
        "Disease, GERD, a couple of years back.",
        "Gastroesophageal Reflux Disease (GERD)."),
    "plan_of_management": (
        "So the plan is, we are going to go ahead and increase her Omeprazole to 20 mg daily, "
        "before breakfast, and I would like to review her in 4 weeks.",
        "Increase Omeprazole to 20 mg daily before breakfast; review in 4 weeks."),
    "diet_instructions": (
        "Diet-wise, um, I want you to eliminate acidic and spicy triggers, cut out late meals, "
        "and remain upright for 3 hours post-meal, okay?",
        "Eliminate acidic and spicy triggers; cut out late meals; remain upright for 3 hours post-meal."),
    "general_instructions": (
        "Also, try to elevate the head of your bed, avoid tight waistwear, and please report "
        "any dysphagia to us immediately.",
        "Elevate head of bed; avoid tight waistwear; report any dysphagia immediately."),
}

# Verified fact kind -> discharge section. The prompt states this map so the
# model does not have to guess where a fact belongs.
PREFILL_SECTION = {"symptom": "present_illness", "vital": "examination_findings",
                   "diagnosis": "previous_diagnosis", "drug": "plan_of_management",
                   "followup": "plan_of_management", "allergy": "general_instructions"}

DISCHARGE = NoteTemplate(
    name="discharge",
    document="discharge note",
    intro="You are a clinical scribe structuring a dictated note.",
    sections=tuple(SectionSpec(k, SECTION_RULES[k], SECTION_EXAMPLES[k], behaves_like=k)
                   for k in BASE_SECTIONS),
    prefill=PREFILL_SECTION,
    schema_line=(
        '{"present_illness": {"items": [{"fact_id": "F1", "text": "...", "source_sentence": "exact sentence heard", "seg_id": 0, "confidence": 0.9}]},\n'
        ' "examination_findings": {"items": [...]}, "previous_diagnosis": {"items": [...]},\n'
        ' "plan_of_management": {"items": [...]}, "diet_instructions": {"items": [...]},\n'
        ' "general_instructions": {"items": [...]}}\n\n'),
    schema_file="discharge.schema.json",
)
