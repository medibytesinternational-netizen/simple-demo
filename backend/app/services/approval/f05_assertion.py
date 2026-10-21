"""F5: record a "no known allergies" statement on an approved note so rule R5 can compare it with the allergy record.

The marker is set only when a claim in the approved draft says it. Nothing is inferred.
"""

from __future__ import annotations

import re
from typing import Any

from . import ApprovalContext, payload_builder

NO_ALLERGY_PATTERN = re.compile(r"no known (drug )?allergies|nkda|\bnka\b", re.IGNORECASE)


def claim_texts(value: Any, out: list[str] | None = None) -> list[str]:
    """Every claim text (a dict with a string `text`) anywhere inside a draft payload."""
    out = [] if out is None else out
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            out.append(value["text"])
        for item in value.values():
            claim_texts(item, out)
    elif isinstance(value, list):
        for item in value:
            claim_texts(item, out)
    return out


def says_no_known_allergies(payload: Any) -> bool:
    return any(NO_ALLERGY_PATTERN.search(text) for text in claim_texts(payload))


@payload_builder("F1")
@payload_builder("F2")
@payload_builder("F3")
@payload_builder("F4")
def mark_no_known_allergies(ctx: ApprovalContext, event_payload: dict[str, Any]) -> None:
    if says_no_known_allergies(ctx.payload):
        event_payload["assertion"] = "no_known_allergies"
