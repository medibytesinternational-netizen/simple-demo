"""Deterministic demo drafts, one module per feature.

Used when no OPENAI_API_KEY is present (or LLM_MODE=cached) and as the fallback when a live call fails.
Every generator must build its text only from the supplied context.
"""

from __future__ import annotations

from typing import Any

from . import (
    f01_consult,
    f02_admission,
    f03_round,
    f04_progress,
    f06_reconciliation,
    f07_icu,
    f09_discharge,
    f10_investigation,
    f11_referral,
    f12_claim,
    f13_leakage,
)
from .labs import f11_investigation  # noqa: F401  (used by the OCR module)

CACHED_GENERATORS = {}
for _module in (
    f01_consult, f02_admission, f03_round, f04_progress, f06_reconciliation, f07_icu,
    f09_discharge, f10_investigation, f11_referral, f12_claim, f13_leakage,
):
    CACHED_GENERATORS.update(_module.GENERATORS)


def cached_draft(feature: str, context: dict[str, Any]) -> dict[str, Any]:
    generator = CACHED_GENERATORS.get(feature)
    if not generator:
        raise ValueError(f"No cached draft for {feature}")
    return generator(context)
