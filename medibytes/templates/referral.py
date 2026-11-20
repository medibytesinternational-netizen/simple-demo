"""F11 - a referral, part one (filled by the referring doctor), in the hospital referral format.

Name, sex, ward and HID number come from the record, and the doctor's name, signature, date and
time are added when the referring doctor approves. These are the headings heard in the dictation.
"""
from __future__ import annotations

from .base import NoteTemplate, SectionSpec, schema_line

SECTIONS = (
    SectionSpec(
        "referral_type",
        "how fast the referral is needed: exactly Immediate (within one hour), Urgent (within four "
        "hours) or Routine (within twenty-four hours), as said (a single item)",
        ("Please see him urgently, within four hours.", "Urgent"),
        behaves_like="plan_of_management", many=False),
    SectionSpec(
        "unit_chief",
        "the doctor (unit chief) the referral is addressed to, by name (a single item)",
        ("I am referring him to Dr. Rao, the cardiology unit chief.", "Dr. Rao"),
        behaves_like="general_instructions", many=False),
    SectionSpec(
        "department",
        "the department or speciality referred to (a single item)",
        ("This is a referral to cardiology.", "Cardiology"),
        behaves_like="plan_of_management", many=False),
    SectionSpec(
        "salient_details",
        "the salient details of the patient and the reason for referral: findings, results, what "
        "the referring doctor asks the specialist, one per item",
        ("He has new onset atrial fibrillation with a rate of 140; please advise on rate control.",
         "New onset atrial fibrillation, rate 140; advice on rate control requested"),
        behaves_like="general_instructions"),
)

KEYS = tuple(s.key for s in SECTIONS)

REFERRAL = NoteTemplate(
    name="referral",
    document="referral form",
    intro="You are a clinical scribe structuring a dictated hospital referral (part one, by the referring doctor).",
    sections=SECTIONS,
    prefill={},
    schema_line=schema_line(KEYS),
    schema_file="",
    extra_rules=(
        "- Use only these headings.\n"
        "- referral_type is exactly Immediate, Urgent or Routine, and only when said or clearly implied by the time asked.\n"
        "- Never guess the doctor's name or department.\n"),
)
