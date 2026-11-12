"""A symptom the patient denies must never reach the note as a present symptom.

Found on a real run (phone40 clip s12): "Denies fever and chest pain." produced
`fever` and `chest pain` as verified present-illness items, and "No cold drinks."
produced `cold`. Two causes: only `chest pain` and `breathlessness` could be marked
denied, and `verify_simple` dropped the `negated` flag, so the note builder never
saw it. Every sentence below is written for the test.
"""
import pytest

from medibytes import verify as V
from medibytes.extraction.entities import extract_entities
from medibytes.extraction.normalize import normalize_text


def _t(text):
    return {"text": text, "normalized_en": normalize_text(text)["normalized_en"]}


def _symptoms(text):
    t = _t(text)
    return {s["text"]: s["negated"] for s in extract_entities(text, t["normalized_en"], [])["symptoms"]}


@pytest.mark.parametrize("sentence, denied", [
    ("Denies fever and chest pain.", {"fever", "chest pain"}),
    ("No vomiting or diarrhea since morning.", {"vomiting", "diarrhea"}),
    ("She has cough but no fever.", {"fever"}),
    ("Patient denies headache.", {"headache"}),
    ("Without breathlessness at rest.", {"breathlessness"}),
])
def test_every_listed_symptom_can_be_denied(sentence, denied):
    found = _symptoms(sentence)
    assert denied <= set(found), found
    assert {s for s, neg in found.items() if neg} == denied, found


def test_a_symptom_before_the_negation_stays_present():
    found = _symptoms("He has cough, no fever.")
    assert found["cough"] is False and found["fever"] is True


def test_a_contrast_ends_the_denial():
    found = _symptoms("No chest pain but has fever.")
    assert found["chest pain"] is True and found["fever"] is False


@pytest.mark.parametrize("sentence", [
    "No cold drinks.", "Avoid cold water and cold foods.", "Take warm fluids, no cold beverages.",
])
def test_cold_in_a_diet_instruction_is_not_a_symptom(sentence):
    assert "cold" not in _symptoms(sentence)


@pytest.mark.parametrize("sentence", ["He has a cold since two days.", "Common cold with cough."])
def test_a_real_cold_is_still_a_symptom(sentence):
    assert "cold" in _symptoms(sentence)


def test_the_verified_fact_keeps_the_denial():
    text = "Denies fever and chest pain. Has cough."
    t = _t(text)
    ents = extract_entities(text, t["normalized_en"], [])
    facts = {f["text"]: f for f in V.verify(t, ents)["facts"] if f["kind"] == "symptom"}
    assert facts["fever"]["negated"] is True and facts["chest pain"]["negated"] is True
    assert facts["cough"]["negated"] is False
