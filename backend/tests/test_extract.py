from __future__ import annotations

from app.services.context import segments_from_transcript
from app.services.extract import analyse, claim, joined_claim

from .helpers import ASTHMA, SHORT_VISIT


def run(text: str):
    return analyse(segments_from_transcript(text))


def texts(sentences):
    return [s.text for s in sentences]


def test_asthma_visit_is_sorted_into_sections():
    result = run(ASTHMA)
    assert "dry cough and wheeze" in result.complaint.text
    assert any("scattered expiratory wheeze" in t for t in texts(result.exam))
    assert any("mild persistent asthma" in t for t in texts(result.assessment))
    assert any("salbutamol" in t for t in texts(result.plan))
    assert any("Review in four weeks" in t for t in texts(result.follow_up))


def test_questions_are_never_findings_or_plans():
    result = run(ASTHMA)
    for section in (result.exam, result.assessment, result.plan, result.follow_up):
        assert all(not s.is_question for s in section)
    assert "Any fever or chest pain?" not in texts(result.exam + result.plan)


def test_medicines_carry_dose_and_frequency_from_the_sentence():
    meds = {m.drug.lower(): m for m in run(ASTHMA).medicines}
    assert set(meds) == {"salbutamol", "beclometasone"}
    assert meds["salbutamol"].dose.lower() == "two puffs"
    assert meds["salbutamol"].frequency.lower() == "as needed"
    assert meds["beclometasone"].dose.lower() == "100 micrograms"
    assert meds["beclometasone"].frequency.lower() == "twice daily"


def test_everything_quoted_was_said():
    result = run(ASTHMA)
    said = ASTHMA
    quoted = [result.complaint, *result.history, *result.exam, *result.assessment, *result.plan, *result.follow_up]
    for sentence in quoted:
        assert sentence.text in said
    for mention in result.medicines:
        assert mention.drug in said and mention.dose in said


def test_a_visit_with_no_clinical_content_documents_nothing():
    result = run(SHORT_VISIT)
    assert not result.exam and not result.plan and not result.assessment
    assert {"Examination", "Assessment", "Plan"} <= set(result.missing())


def test_claims_cite_their_segment():
    result = run(ASTHMA)
    first = claim(result.complaint, "evt_x")
    assert first["source_event_ids"] == ["evt_x"]
    assert first["source_segment_ids"] == [result.complaint.segment_id]
    both = joined_claim(result.exam, "evt_x")
    assert both["text"] in ASTHMA.replace("\n", " ") or all(t in ASTHMA for t in texts(result.exam))
    assert joined_claim([]) is None


def test_nurse_lines_are_kept_apart():
    text = "Doctor: Check potassium this morning.\nNurse: Understood, I will repeat the bloods."
    result = run(text)
    assert texts(result.nurse_lines) == ["Understood, I will repeat the bloods."]
    assert texts(result.plan) == ["Check potassium this morning."]
