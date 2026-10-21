from __future__ import annotations

from typing import Any

from . import ApprovalContext, validator


def unverified_allergies(payload: dict[str, Any]) -> list[str]:
    allergies = payload.get("allergies_to_verify") or []
    return [
        item.get("substance", "unknown")
        for item in allergies
        if isinstance(item, dict) and not item.get("verified")
    ]


@validator("F2")
def require_verified_allergies(ctx: ApprovalContext) -> None:
    unverified = unverified_allergies(ctx.payload)
    if unverified:
        raise ValueError(
            "F2 cannot be approved: verify the documented allergy record first "
            f"({', '.join(unverified)}). The model may not mark an allergy as verified."
        )
