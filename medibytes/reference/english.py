"""Everyday English words, so a long ordinary word is never taken for a drug."""
from __future__ import annotations

from ..config import ASSETS_DIR

_ENGLISH: set[str] | None = None
_SUFFIXES = ("ing", "ed", "es", "s", "ly", "er", "ers", "ion", "ions")


def _english() -> set[str]:
    global _ENGLISH
    if _ENGLISH is None:
        with open(ASSETS_DIR / "english_words.txt", encoding="utf-8") as f:
            _ENGLISH = {line.strip() for line in f if line.strip()}
    return _ENGLISH


def is_ordinary_word(low: str) -> bool:
    """An everyday English word, or an inflection of one (`boosting` <- `boost`)."""
    words = _english()
    if low in words:
        return True
    for suffix in _SUFFIXES:
        if low.endswith(suffix) and len(low) - len(suffix) >= 4:
            stem = low[:-len(suffix)]
            if stem in words or stem + "e" in words:
                return True
    return False
