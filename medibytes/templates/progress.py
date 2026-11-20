"""F4 - a daily progress note entry (doctor's or nurse's), one row of the progress notes table.

The row's date, time, name and sign come from the record; the only heading heard is the note.
"""
from __future__ import annotations

from .base import NoteTemplate, SectionSpec, schema_line

SECTIONS = (
    SectionSpec(
        "notes",
        "each observation, finding, change, treatment given or plan said in today's progress note, "
        "one per item, in the order said",
        ("Patient is afebrile since morning and tolerating oral feeds.",
         "Afebrile since morning, tolerating oral feeds"),
        behaves_like="general_instructions"),
)

KEYS = tuple(s.key for s in SECTIONS)

PROGRESS = NoteTemplate(
    name="progress",
    document="daily progress note",
    intro="You are a clinical scribe structuring a dictated daily progress note (doctor's or nurse's).",
    sections=SECTIONS,
    prefill={},
    schema_line=schema_line(KEYS),
    schema_file="",
    extra_rules=(
        "- Use only the notes heading.\n"
        "- Keep each item short and as said. Never add findings nobody spoke about.\n"),
)
