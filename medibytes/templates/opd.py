"""F1 - the OPD (outpatient) consultation note, in the hospital's OPD format.

The format's record headings (patient name, age and sex, date of admission, hospital number,
department, unit and consultant, recorded by) come from registration, not from speech, so they are
not sections here. These are the headings heard in the consultation, in the format's order.
"""
from __future__ import annotations

from .base import NoteTemplate, SectionSpec, schema_line

SECTIONS = (
    SectionSpec(
        "mode_of_admission",
        "how the patient came: walked in, brought by family, by ambulance, referred, "
        "from emergency (a single item)",
        ("He came by himself, walked in to the OPD this morning.",
         "Walked in to the OPD."),
        behaves_like="general_instructions", many=False),
    SectionSpec(
        "referring_physician",
        "the doctor or hospital that referred the patient, as named (a single item)",
        ("Dr. Rao from the town clinic sent her to us with a letter.",
         "Referred by Dr. Rao, town clinic."),
        behaves_like="general_instructions", many=False),
    SectionSpec(
        "previous_admission",
        "earlier hospital admissions: where, when and why (a single item)",
        ("She was admitted at City Hospital last year for pneumonia.",
         "Admitted at City Hospital last year for pneumonia."),
        behaves_like="previous_diagnosis", many=False),
    SectionSpec(
        "previous_diagnosis",
        "conditions diagnosed before this visit: known illnesses, surgeries, one per item",
        ("He is a known diabetic for ten years and had his gallbladder removed.",
         "Known diabetic for ten years; gallbladder removed."),
        behaves_like="previous_diagnosis"),
    SectionSpec(
        "allergies",
        "each allergy, starting with Food:, Drug: or Other:, with the reaction; "
        "\"No known allergies\" if the patient says so",
        ("She says penicillin gives her a rash and she cannot eat prawns.",
         "Drug: penicillin - rash"),
        behaves_like="general_instructions"),
    SectionSpec(
        "pain",
        "the pain: site, duration, score out of 10, frequency, and where it spreads to, "
        "only the parts that were said (a single item)",
        ("The pain is in the lower back for three weeks, about seven out of ten, comes "
         "every evening and goes down the left leg.",
         "Lower back, 3 weeks, 7/10, every evening, radiates down the left leg."),
        behaves_like="present_illness", many=False),
    SectionSpec(
        "occupation",
        "the patient's work (a single item)",
        ("I work as a school teacher.", "School teacher."),
        behaves_like="general_instructions", many=False),
    SectionSpec(
        "source_of_history",
        "who gave the history and how reliable it is (a single item)",
        ("The history is from his wife, who is with him all the time, so it is reliable.",
         "From the wife, who is with him all the time; reliable."),
        behaves_like="general_instructions", many=False),
    SectionSpec(
        "chief_complaints",
        "the main complaints that brought the patient today, each with its duration, "
        "one per item",
        ("Mainly this cough for two weeks, and the fever since three days.",
         "Cough for two weeks."),
        behaves_like="present_illness"),
    SectionSpec(
        "history_of_present_illness",
        "the story of the current illness: onset, course, triggers, associated and "
        "denied symptoms, one per item (prefix DENIED: if marked DENIED)",
        ("It started after a cold, it gets worse at night, and she also mentions some "
         "mild wheezing when she climbs stairs.",
         "Started after a cold; worse at night; mild wheezing when she climbs stairs."),
        behaves_like="present_illness"),
)

KEYS = tuple(s.key for s in SECTIONS)

OPD = NoteTemplate(
    name="opd",
    document="OPD consultation note",
    intro="You are a clinical scribe structuring a dictated OPD (outpatient) consultation note "
          "in the hospital's OPD format.",
    sections=SECTIONS,
    prefill={"symptom": "history_of_present_illness", "diagnosis": "previous_diagnosis",
             "allergy": "allergies"},
    schema_line=schema_line(KEYS),
    schema_file="",
    extra_rules=(
        "- Use only these headings. Examination, medicines, tests and plans are not part of "
        "this format: leave them out.\n"
        "- chief_complaints are the reasons for today's visit; the story of the illness goes "
        "in history_of_present_illness.\n"
        "- previous_diagnosis is what was diagnosed BEFORE this visit, never today's impression.\n"
        "- Leave a heading empty when nobody spoke about it. Never guess the mode of admission, "
        "the source of history or the occupation.\n"),
)
