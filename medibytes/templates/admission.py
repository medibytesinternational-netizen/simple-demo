"""F2 - the admission note, in the hospital's admission format.

The record headings (name, sex, age, OP number, date, consultant) come from registration, so they
are not sections here. These are the headings heard when the doctor dictates the admission.
"""
from __future__ import annotations

from .base import NoteTemplate, SectionSpec, schema_line

SECTIONS = (
    SectionSpec(
        "admission_type",
        "whether the admission is Elective or Emergency, as said (a single item)",
        ("We are admitting him as an emergency tonight.", "Emergency"),
        behaves_like="plan_of_management", many=False),
    SectionSpec(
        "ward",
        "the ward or unit the patient is admitted to, as named (a single item)",
        ("Please admit her to the medical ward, Ward 5.", "Medical ward, Ward 5"),
        behaves_like="plan_of_management", many=False),
    SectionSpec(
        "speciality",
        "the speciality or department taking the patient (a single item)",
        ("She will be under general medicine.", "General medicine"),
        behaves_like="plan_of_management", many=False),
    SectionSpec(
        "provisional_diagnosis",
        "the working diagnosis for this admission, one per item",
        ("The provisional diagnosis is community acquired pneumonia.",
         "Community acquired pneumonia"),
        behaves_like="previous_diagnosis"),
    SectionSpec(
        "proposed_treatment",
        "the treatment planned in hospital: medicines with dose, procedures, therapy, one per item",
        ("We will start IV ceftriaxone 1 g twice daily and oxygen to keep saturation above 94.",
         "IV ceftriaxone 1 g twice daily"),
        behaves_like="plan_of_management"),
    SectionSpec(
        "expected_outcome",
        "the expected outcome: Improved, Unchanged or Worsened (a single item)",
        ("I expect him to improve within a few days.", "Improved"),
        behaves_like="plan_of_management", many=False),
    SectionSpec(
        "possible_complications",
        "complications the doctor says may happen, one per item",
        ("There is a risk of sepsis and of respiratory failure.", "Sepsis"),
        behaves_like="plan_of_management"),
    SectionSpec(
        "allergies",
        "each allergy, starting with Food:, Drug: or Other:, with the reaction; "
        "\"No known allergies\" if said",
        ("He is allergic to penicillin, it gives a rash.", "Drug: penicillin - rash"),
        behaves_like="general_instructions"),
    SectionSpec(
        "cost_category",
        "the approximate cost or the payment category (general, private, insurance, scheme) "
        "(a single item)",
        ("This will be under the insurance category, roughly fifty thousand.",
         "Insurance, approximately 50,000"),
        behaves_like="general_instructions", many=False),
    SectionSpec(
        "admission_labs",
        "each blood or lab test ordered on admission, one per item",
        ("Send a CBC, renal function and blood cultures.", "Complete blood count"),
        behaves_like="plan_of_management"),
    SectionSpec(
        "imaging_studies",
        "each imaging study ordered: x-ray, ultrasound, CT, MRI, echo, one per item",
        ("Get a chest x-ray and an ultrasound of the abdomen.", "Chest x-ray"),
        behaves_like="plan_of_management"),
    SectionSpec(
        "consultations_required",
        "each specialist opinion or referral requested, one per item",
        ("We need a cardiology opinion before surgery.", "Cardiology opinion"),
        behaves_like="plan_of_management"),
)

KEYS = tuple(s.key for s in SECTIONS)

ADMISSION = NoteTemplate(
    name="admission",
    document="admission note",
    intro="You are a clinical scribe structuring a dictated hospital admission note in the "
          "hospital's admission format.",
    sections=SECTIONS,
    prefill={"diagnosis": "provisional_diagnosis", "drug": "proposed_treatment", "allergy": "allergies"},
    schema_line=schema_line(KEYS),
    schema_file="",
    extra_rules=(
        "- Use only these headings.\n"
        "- admission_type is exactly Elective or Emergency, and only when said.\n"
        "- expected_outcome is exactly Improved, Unchanged or Worsened, and only when said.\n"
        "- Tests go in admission_labs, scans in imaging_studies, specialist opinions in "
        "consultations_required; medicines and procedures in proposed_treatment.\n"
        "- Leave a heading empty when nobody spoke about it. Never guess the ward, cost or outcome.\n"),
)
