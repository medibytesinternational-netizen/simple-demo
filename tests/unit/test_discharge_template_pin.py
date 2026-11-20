"""The discharge template is the measured one: its prompts and hardening must not move.

Snapshots were taken from the code before templates existed (Phone40 clip s1).
"""
import json
from pathlib import Path

from tests.unit import _prompt_snapshot as snap

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_discharge_prompts_are_byte_identical_to_before_templates():
    want = _load("discharge_prompts_s1.json")
    got = snap.prompts()
    for key in want:
        assert got[key] == want[key], key


def test_discharge_hardening_is_identical_to_before_templates():
    want = _load("discharge_hardening_s1.json")
    got = json.loads(json.dumps(snap.hardening(), ensure_ascii=False))
    for key in want:
        assert got[key] == want[key], key
