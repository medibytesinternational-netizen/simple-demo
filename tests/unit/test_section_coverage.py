"""The section-coverage benchmark: script parsing and part matching."""
from evaluation.phone40.section_coverage import SCRIPTS, part_reached, score_note, script_sections

S12 = (SCRIPTS / "s12.txt").read_text(encoding="utf-8")


def test_a_labelled_script_splits_into_its_six_sections():
    s = script_sections(S12)
    assert s["examination_findings"][-1] == "bilateral wheeze"
    assert s["previous_diagnosis"] == ["bronchial asthma", "moderate exacerbation"]
    assert s["plan_of_management"][0] == "nebulised salbutamol"
    assert s["plan_of_management"][-1] == "Follow up in two days"   # unlabelled follow-up
    assert s["diet_instructions"] == ["warm fluids", "no cold drinks", "normal vegetarian diet"]
    assert s["general_instructions"][0] == "carry reliever"
    assert not any("fever" in p for parts in s.values() for p in parts)  # the denial is skipped


def test_parts_match_through_number_words_and_misspellings():
    part = "prednisolone forty milligrams daily five days"
    assert part_reached(part, [{"text": "prednisolone 40 mg daily for 5 days"}])
    assert not part_reached(part, [{"text": "prednisolone 40 mg"}])  # the schedule is lost
    assert part_reached("correct inhaler technique", [{"text": "currect inhaler technique"}])
    assert not part_reached("carry reliever", [{"text": "correct inhaler technique"}])


def test_a_note_scores_per_section():
    note = {"sections": {"diet_instructions": {"items": [{"text": "Warm fluids"}]},
                         "general_instructions": {"items": []}}}
    scored = score_note(S12, note)
    assert scored["diet_instructions"]["reached"] == 1 and scored["diet_instructions"]["parts"] == 3
    assert scored["general_instructions"]["filled"] is False
