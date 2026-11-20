"""Consultation note written from the conversation only, by quoting it, in the hospital OPD format.

Used when there is no AI key and as the fallback when a live model call fails or returns nothing.
Every claim is a verbatim sentence from the transcript and cites the segment it came from. A heading
nobody spoke about stays empty and is listed under ``not_documented``. The record headings (name,
hospital number, consultant...) are added from registration when the draft is created.
"""

from __future__ import annotations

import re
from typing import Any

from ..extract import analyse, claim, joined_claim
from ..opd import OPD_FORMAT, heard_not_documented

# Sentence finders for the headings the general analyser does not sort.
_FIND = {
    "mode_of_admission": re.compile(
        r"\b(walk(?:ed|s)? in|came (?:by|on) (?:him|her|them)sel(?:f|ves)|brought (?:in )?by|by ambulance|"
        r"from (?:the )?(?:emergency|casualty)|came (?:through|via) (?:the )?(?:emergency|casualty))\b", re.I),
    "referring_physician": re.compile(r"\b(referred (?:by|from)|referral (?:from|letter)|sent (?:him|her|them|me) (?:here|to us))\b", re.I),
    "previous_admission": re.compile(r"\b(admitted|hospitali[sz]ed|admission)\b.*\b(before|last|ago|previous(?:ly)?|earlier|in \d{4})\b|\bprevious(?:ly)? admitted\b", re.I),
    "previous_diagnosis": re.compile(r"\b(known (?:case|diabetic|hypertensive)|diagnosed with|history of|k/c/o|had (?:a|an|his|her) \w+ (?:removed|operation|surgery))\b", re.I),
    "allergies": re.compile(r"\ballerg(?:y|ies|ic)\b", re.I),
    "pain": re.compile(r"\b(pain|ache|aching|hurts?|sore)\b", re.I),
    "occupation": re.compile(r"\b(work(?:s|ing)? (?:as|in|at)|by profession|occupation|i am a (?:teacher|farmer|driver|nurse|clerk|labourer|student|shopkeeper|engineer)|retired)\b", re.I),
    "source_of_history": re.compile(r"\b((?:history|information) (?:is )?(?:given|provided|obtained) by|accompanied by|"
                                    r"(?:his|her) (?:wife|husband|son|daughter|mother|father) (?:says|tells|reports|gives)|reliab(?:le|ility))\b", re.I),
}


def f1_consult_note(context: dict[str, Any]) -> dict[str, Any]:
    transcript = context.get("transcript") or {}
    tid = transcript.get("event_id", "")
    analysis = analyse(transcript.get("segments", []))
    sentences = analysis.sentences

    # A question asked is not something the patient said about themselves.
    said = [s for s in sentences if not s.is_question]
    found: dict[str, list[Any]] = {key: [s for s in said if rx.search(s.text)] for key, rx in _FIND.items()}
    # An allergy sentence is not a past diagnosis.
    found["previous_diagnosis"] = [s for s in found["previous_diagnosis"] if s not in found["allergies"]]

    complaints = [analysis.complaint] if analysis.complaint else []
    # The history keeps every history sentence in the order said (so it stays one run of quotes);
    # a sentence may also appear under Pain or Allergies.
    history = [s for s in analysis.history if s is not analysis.complaint]

    content: dict[str, Any] = {
        "format": OPD_FORMAT,
        "mode_of_admission": joined_claim(found["mode_of_admission"][:1], tid),
        "referring_physician": joined_claim(found["referring_physician"][:1], tid),
        "previous_admission": joined_claim(found["previous_admission"], tid),
        "previous_diagnosis": [claim(s, tid) for s in found["previous_diagnosis"]],
        # Quoted as said: the sentence itself names the food, drug or other trigger.
        "allergies": [claim(s, tid) for s in found["allergies"]],
        "pain": joined_claim(found["pain"], tid),
        "occupation": joined_claim(found["occupation"][:1], tid),
        "source_of_history": joined_claim(found["source_of_history"], tid),
        "chief_complaints": [claim(s, tid) for s in complaints],
        "history_of_present_illness": joined_claim(history, tid),
    }
    content["not_documented"] = heard_not_documented(content)
    return content


GENERATORS = {"F1": f1_consult_note}
