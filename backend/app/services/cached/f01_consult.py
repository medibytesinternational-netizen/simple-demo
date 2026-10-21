"""Consultation note written from the conversation only, by quoting it.

Used when there is no AI key and as the fallback when a live model call fails or returns nothing.
Every claim is a verbatim sentence from the transcript and cites the segment it came from. A section
nobody spoke about stays empty and is listed under ``not_documented``. Nothing is taken from the
patient record: a consultation note comes from the consultation.
"""

from __future__ import annotations

from typing import Any

from ..extract import analyse, claim, joined_claim


def f1_consult_note(context: dict[str, Any]) -> dict[str, Any]:
    transcript = context.get("transcript") or {}
    transcript_id = transcript.get("event_id", "")
    analysis = analyse(transcript.get("segments", []))

    # The complaint is already its own claim, so the history does not repeat it.
    history = [sentence for sentence in analysis.history if sentence is not analysis.complaint]
    # An instruction or a review date is not an examination finding.
    instructions = set(analysis.plan) | set(analysis.follow_up)
    exam = [sentence for sentence in analysis.exam if sentence not in instructions]

    hpi = joined_claim(history, transcript_id)
    general = joined_claim(exam, transcript_id)

    not_documented = analysis.missing()
    if hpi is None and "History" not in not_documented:
        not_documented.append("History")
    if general is None and "Examination" not in not_documented:
        not_documented.append("Examination")

    return {
        "chief_complaint": claim(analysis.complaint, transcript_id) if analysis.complaint else None,
        "hpi": hpi,
        "exam": {"general": general, "systemic": None},
        "assessment": [claim(sentence, transcript_id) for sentence in analysis.assessment],
        "plan": [claim(sentence, transcript_id) for sentence in analysis.plan],
        "medication_mentions": [
            {
                "drug": mention.drug,
                "dose": mention.dose,
                "frequency": mention.frequency,
                "source_event_ids": [transcript_id] if transcript_id else [],
                "source_segment_ids": [mention.sentence.segment_id],
            }
            for mention in analysis.medicines
        ],
        "follow_up": joined_claim(analysis.follow_up, transcript_id),
        "not_documented": not_documented,
    }


GENERATORS = {"F1": f1_consult_note}
