"""Note formats stage 7 can write. ``discharge`` is the default and the measured one."""
from __future__ import annotations

from .base import BASE_SECTIONS, NoteTemplate, SectionSpec
from .discharge import DISCHARGE
from .opd import OPD
from .admission import ADMISSION
from .progress import PROGRESS
from .referral import REFERRAL

TEMPLATES: dict[str, NoteTemplate] = {t.name: t for t in (DISCHARGE, OPD, ADMISSION, PROGRESS, REFERRAL)}


def get(name: str | NoteTemplate | None) -> NoteTemplate:
    if isinstance(name, NoteTemplate):
        return name
    if not name:
        return DISCHARGE
    try:
        return TEMPLATES[name]
    except KeyError:
        raise ValueError(f"unknown note template {name!r}; known: {sorted(TEMPLATES)}") from None


__all__ = ["BASE_SECTIONS", "DISCHARGE", "NoteTemplate", "SectionSpec", "TEMPLATES", "get"]
