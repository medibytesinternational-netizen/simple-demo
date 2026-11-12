"""F1 - the OPD (outpatient) consultation note.

Maps onto the app's ConsultNote: chief complaint, history, examination (general and
systemic), assessment, medicines, investigations, plan, advice and follow-up.
"""
from __future__ import annotations

from .base import NoteTemplate, SectionSpec, schema_line

SECTIONS = (
    SectionSpec(
        "chief_complaint",
        "the ONE main complaint that brought the patient today, with its duration "
        "(a single item)",
        ("Okay so she has come in today mainly because of this cough, which has been "
         "going on for about two weeks now.",
         "Cough for two weeks."),
        behaves_like="present_illness", many=False),
    SectionSpec(
        "history_of_present_illness",
        "every other current symptom, its onset, course and triggers, one per item "
        "(prefix DENIED: if marked DENIED)",
        ("It started after a cold, it gets worse at night, and she also mentions some "
         "mild wheezing when she climbs stairs.",
         "Started after a cold; worse at night; mild wheezing when she climbs stairs."),
        behaves_like="present_illness"),
    SectionSpec(
        "past_history",
        "past illnesses, known conditions, surgeries and family history",
        ("She is a known case of hypertension for the last five years and had her "
         "appendix removed as a child.",
         "Known case of hypertension for five years; appendix removed as a child."),
        behaves_like="previous_diagnosis"),
    SectionSpec(
        "examination_general",
        "vital-sign readings and the general examination (built, pallor, icterus, "
        "oedema, hydration)",
        ("On general examination she is comfortable, no pallor, no pedal oedema, and "
         "she is well hydrated.",
         "Comfortable; no pallor; no pedal oedema; well hydrated."),
        behaves_like="examination_findings"),
    SectionSpec(
        "examination_systemic",
        "system-by-system findings: chest, heart, abdomen, nervous system, local exam",
        ("On auscultation of the chest there are scattered wheezes on both sides, the "
         "heart sounds are normal and the abdomen is soft.",
         "Chest: scattered wheezes on both sides; heart sounds normal; abdomen soft."),
        behaves_like="examination_findings"),
    SectionSpec(
        "assessment",
        "the diagnosis or impression the doctor makes at THIS visit "
        "(provisional or differential included)",
        ("So my impression is that this is most likely an acute exacerbation of "
         "asthma, triggered by the viral infection.",
         "Acute exacerbation of asthma triggered by viral infection."),
        behaves_like="previous_diagnosis"),
    SectionSpec(
        "medications",
        "each medicine prescribed, continued, changed or stopped, with dose, unit, "
        'route and frequency, one per item (prefix "NOT GIVEN: " if marked NOT GIVEN)',
        ("We will start her on Montelukast 10 mg once at night and continue the "
         "Salbutamol inhaler as needed.",
         "Montelukast 10 mg once at night; continue Salbutamol inhaler as needed."),
        behaves_like="plan_of_management"),
    SectionSpec(
        "investigations",
        "every test ordered: blood tests, imaging, ECG, spirometry, cultures",
        ("I would also like a complete blood count and a chest x-ray done before she "
         "comes back.",
         "Complete blood count; chest x-ray."),
        behaves_like="plan_of_management"),
    SectionSpec(
        "plan",
        "management other than medicines and tests: referrals, procedures, therapy, "
        "admission",
        ("If it does not settle I am going to refer her to the pulmonology clinic for "
         "a detailed review.",
         "Refer to pulmonology clinic for detailed review."),
        behaves_like="plan_of_management"),
    SectionSpec(
        "advice",
        "diet, lifestyle and warning-sign advice actually spoken, and allergy "
        "statements (prefix DENIED if denied)",
        ("Please avoid dust and cold drinks, and come straight back if the "
         "breathlessness gets worse.",
         "Avoid dust and cold drinks; come back if breathlessness gets worse."),
        behaves_like="general_instructions"),
    SectionSpec(
        "follow_up",
        "when and where the patient should be reviewed next",
        ("Let us review her again in the clinic after one week with the reports.",
         "Review in the clinic after one week with the reports."),
        behaves_like="plan_of_management"),
)

KEYS = tuple(s.key for s in SECTIONS)

OPD = NoteTemplate(
    name="opd",
    document="OPD consultation note",
    intro="You are a clinical scribe structuring a dictated OPD (outpatient) consultation note.",
    sections=SECTIONS,
    prefill={"symptom": "history_of_present_illness", "vital": "examination_general",
             "diagnosis": "assessment", "drug": "medications",
             "followup": "follow_up", "allergy": "advice"},
    schema_line=schema_line(KEYS),
    schema_file="",
    extra_rules=(
        "- chief_complaint holds ONE item only: the main reason for the visit. Every other "
        "symptom goes in history_of_present_illness.\n"
        "- Medicines go ONLY in medications (never in plan); tests ordered go ONLY in "
        "investigations.\n"
        "- assessment is what the doctor concludes TODAY; known old conditions go in "
        "past_history.\n"),
)
