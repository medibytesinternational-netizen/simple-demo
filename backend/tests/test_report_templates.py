from __future__ import annotations

from app.db import SessionLocal
from app.services.report_templates import generate_report_template


def _note(**values):
    return {
        "present_illness": values.get("present_illness", ""),
        "examination_findings": values.get("examination_findings", ""),
        "previous_diagnosis": values.get("previous_diagnosis", ""),
        "plan_of_management": values.get("plan_of_management", ""),
        "diet_instructions": values.get("diet_instructions", ""),
        "general_instructions": values.get("general_instructions", ""),
    }


def _generate(feature, note, warnings=None):
    with SessionLocal() as db:
        content, call = generate_report_template(db, feature, note, warnings or [], "evt-source")
        db.rollback()
    return content, call


def test_opd_template_keeps_only_supported_claims_and_review_warnings():
    warnings = [{"section": "present_illness", "text": "Check the duration."}]
    content, call = _generate("F1", _note(present_illness="Cough for two weeks."), warnings)
    assert content["format"] == "opd_v2"
    assert content["chief_complaints"][0]["text"] == "Cough for two weeks."
    assert content["history_of_present_illness"]["text"] == "Cough for two weeks."
    assert content["mode_of_admission"] is None
    assert "Mode of admission" in content["not_documented"]
    assert content["needs_review"] == warnings
    assert call.mode == "cached"


def test_admission_fields_missing_from_api_stay_empty():
    note = _note(plan_of_management="Start IV ceftriaxone 1 g twice daily. Get a chest x-ray.")
    content, _ = _generate("F2", note)
    assert content["format"] == "admit_v2"
    assert content["admission_type"] is None and content["ward"] is None
    assert content["proposed_treatment"][0]["text"] == "Start IV ceftriaxone 1 g twice daily."
    assert content["imaging_studies"][0]["text"] == "Get a chest x-ray."
    assert "Elective or emergency" in content["not_documented"]
    assert "Admit to ward" in content["not_documented"]


def test_referral_unit_chief_stays_empty_and_review_items_reach_the_form():
    warnings = [{"section": "plan_of_management", "text": "Check the referral urgency."}]
    note = _note(plan_of_management="Urgent referral to Cardiology; please advise on rate control.")
    content, _ = _generate("F11", note, warnings)
    assert content["format"] == "referral_v2"
    assert content["referral_type"] == "urgent"
    assert content["department"]["text"] == "Cardiology"
    assert content["unit_chief"] is None
    assert "Unit chief requested of" in content["not_documented"]
    assert content["needs_review"] == warnings


def test_progress_note_uses_all_six_source_sections_without_rewriting_them():
    note = _note(present_illness="Afebrile today.", examination_findings="Chest clear.", plan_of_management="Review tomorrow.")
    content, _ = _generate("F4", note)
    assert content["format"] == "progress_v2"
    assert [item["text"] for item in content["notes"]] == ["Afebrile today.", "Chest clear.", "Review tomorrow."]
    assert all(item["source_event_ids"] == ["evt-source"] for item in content["notes"])
