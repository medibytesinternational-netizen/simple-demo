"""Admission allergy gate (no frontend runner: static checks).

A clinician may only attest to an allergy record they can see. When the record could not be
read (``allergiesKnown`` is false) the page must not offer the verification checkbox, must say
why, and validation must fail whatever the checkbox state. A verification is stored as the id
of the patient whose record was verified, so it can never authorise a different patient.

Limitation: the repository has no frontend test runner, so these tests inspect the TypeScript
source. They prove the code is wired as reviewed (the rule order, which value validation reads,
what the checkbox binds to); they cannot prove runtime behaviour such as React render timing.
That was checked separately in a browser (the patient-switch race) and is not repeated here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _frontend(*parts: str) -> str:
    src = ROOT / "frontend" / "src"
    if not src.exists():
        pytest.skip(f"frontend source not present: {src}")
    # A missing file under a present frontend is a failure, not a skip: the gate must exist.
    return src.joinpath(*parts).read_text(encoding="utf-8")


def _gate_body() -> str:
    source = _frontend("components", "admissionRules.ts")
    start = source.index("export function allergyGateError(")
    return source[start: source.index("\n}\n", start)]


# ---------- unavailable record ----------

def test_the_unavailable_message_is_the_reviewed_wording():
    source = _frontend("components", "admissionRules.ts")
    assert 'ALLERGY_UNAVAILABLE = "The allergy record must be available before admission"' in source


def test_an_unavailable_record_fails_before_the_checkbox_is_consulted():
    body = _gate_body()
    unavailable = body.index("if (!allergiesKnown) return ALLERGY_UNAVAILABLE;")
    # The checkbox is read only after the unavailable branch has returned, so a ticked box cannot pass.
    assert unavailable < body.index("if (!verified)")
    assert body.count("return null;") == 1 and body.index("return null;") > unavailable


def test_admission_validation_uses_the_gate_with_the_patients_record_state():
    page = _frontend("pages", "Admission.tsx")
    validate = page[page.index("function validate()"): page.index("function submit()")]
    # Verified means "verified for this patient", not "a box was ticked at some point".
    assert "allergyGateError(patient ? patient.allergiesKnown : true, form.allergyVerifiedFor === patient?.id)" in validate
    assert "if (allergyError) e.allergyVerified = allergyError;" in validate


def test_the_checkbox_is_not_offered_for_an_unavailable_record():
    page = _frontend("pages", "Admission.tsx")
    gate = page.index("{patient.allergiesKnown ? (")
    checkbox = page.index("I have verified this allergy record")
    fallback = page.index('data-testid="allergy-unavailable">{ALLERGY_UNAVAILABLE}</div>')
    assert gate < checkbox < fallback
    assert page.count("I have verified this allergy record") == 1


def test_a_verification_is_bound_to_the_patient_it_was_given_for():
    page = _frontend("pages", "Admission.tsx")
    # Stored as a patient id (or null), never as a bare flag.
    assert 'allergyVerifiedFor: null as string | null' in page
    # Ticking stores this patient's id; unticking clears it.
    assert 'onChange={(e) => set("allergyVerifiedFor", e.target.checked ? patient.id : null)}' in page
    # The box shows as ticked only for the patient it was verified for.
    assert "checked={form.allergyVerifiedFor === patient.id}" in page


def test_no_patient_independent_verification_flag_or_reset_effect_remains():
    page = _frontend("pages", "Admission.tsx")
    # A flag cleared by an effect leaves a window where the old tick meets the new patient.
    assert not re.search(r"\ballergyChecked\b", page)  # (allergyCheckedBy, the preview record's checker, is unrelated)
    assert not re.search(r"useEffect\(", page), "verification must not depend on an effect to clear it"


def test_an_unavailable_record_is_never_shown_as_nkda():
    page = _frontend("pages", "Admission.tsx")
    assert (
        'patient.allergiesKnown ? "No known drug allergies recorded" : "Allergy record not available in this view.'
        in page
    )


# ---------- available record ----------

def test_an_available_record_still_needs_the_clinician_to_verify_it():
    body = _gate_body()
    assert "if (!verified) return ALLERGY_NOT_VERIFIED;" in body
    source = _frontend("components", "admissionRules.ts")
    assert 'ALLERGY_NOT_VERIFIED = "A clinician must verify the allergy record before admission."' in source


def test_an_available_record_keeps_the_checkbox_and_its_error():
    page = _frontend("pages", "Admission.tsx")
    available = page[page.index("{patient.allergiesKnown ? ("): page.index('data-testid="allergy-unavailable"')]
    assert "checked={form.allergyVerifiedFor === patient.id}" in available
    assert 'err("allergyVerified")' in available
