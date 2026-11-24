import json

import pytest

from app.services.medibytes_note import (
    NOTE_FIELDS,
    MediBytesNoteError,
    format_note_sections,
    note_segments,
    parse_note_response,
)


NOTE = {
    "present_illness": "Symptoms described in the recording.",
    "examination_findings": "",
    "previous_diagnosis": "",
    "plan_of_management": "Follow-up stated.",
    "diet_instructions": "",
    "general_instructions": "",
}


def test_parses_the_six_section_json_array_and_preserves_empty_sections():
    response = json.dumps([NOTE], separators=(",", ":"))
    assert tuple(parse_note_response(response)) == NOTE_FIELDS
    assert parse_note_response(response) == NOTE
    formatted = format_note_sections(NOTE)
    assert "Symptoms described in the recording." in formatted
    assert "Examination findings:\n\n" in formatted
    assert "Not documented" not in formatted


@pytest.mark.parametrize(
    "response",
    [
        "",
        "null",
        "{}",
        "[]",
        json.dumps([NOTE, NOTE]),
        json.dumps([{key: value for key, value in NOTE.items() if key != "diet_instructions"}]),
        json.dumps([{**NOTE, "plan_of_management": None}]),
        json.dumps([{**NOTE, "unexpected": "value"}]),
    ],
)
def test_rejects_payloads_outside_the_documented_shape(response):
    with pytest.raises(MediBytesNoteError):
        parse_note_response(response)


def test_segments_use_only_nonempty_fields_and_do_not_invent_timestamps():
    segments = note_segments(NOTE)
    assert len(segments) == 2
    assert {segment["section"] for segment in segments} == {"present_illness", "plan_of_management"}
    assert all("start_seconds" not in segment and "end_seconds" not in segment for segment in segments)
