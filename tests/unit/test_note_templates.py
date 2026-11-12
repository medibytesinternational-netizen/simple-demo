"""Every note template is internally consistent and its examples teach trimming, not rewording."""
import re

import pytest

from medibytes.llm import discharge as d
from medibytes.templates import BASE_SECTIONS, TEMPLATES

WORD = re.compile(r"[a-z0-9][a-z0-9'-]*")


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_every_section_behaves_like_a_discharge_section(name):
    t = TEMPLATES[name]
    assert t.keys and len(set(t.keys)) == len(t.keys)
    assert all(t.base(k) in BASE_SECTIONS for k in t.keys)
    assert set(t.prefill.values()) <= set(t.keys)


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_example_items_only_use_words_from_their_sentence(name):
    t = TEMPLATES[name]
    for k in t.keys:
        sentence, item = t.example(k)
        said = set(WORD.findall(sentence.lower()))
        extra = [w for w in WORD.findall(item.lower()) if w not in said]
        assert not extra, f"{name}.{k}: {extra}"


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_prompts_name_every_section_and_only_this_templates(name):
    t = TEMPLATES[name]
    prompt = d._discharge_prompt("Cough for two weeks.", "Cough for two weeks.", {"facts": []}, [], None, t)
    assert prompt.startswith(t.intro)
    for k in t.keys:
        assert f"- {k}: " in prompt
    others = {k for o in TEMPLATES.values() for k in o.keys} - set(t.keys)
    assert not any(f"- {k}: " in prompt for k in others)
    analyse = d._analyse_prompt("Cough for two weeks.", t)
    assert t.document in analyse


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_an_empty_note_of_every_template_is_schema_valid(name):
    t = TEMPLATES[name]
    note = {"sections": {k: {"items": []} for k in t.keys}, "provenance": {}}
    assert d.validate_discharge(note, t) == (True, [])
    bad = {"sections": {**note["sections"], "not_a_section": {"items": []}}}
    assert d.validate_discharge(bad, t)[0] is False
