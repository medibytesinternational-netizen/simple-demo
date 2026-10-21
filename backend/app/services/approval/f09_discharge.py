from __future__ import annotations

from typing import Any

from ...db import utcnow
from . import ApprovalContext, after_commit


@after_commit("F9")
def close_encounter(ctx: ApprovalContext, event: Any) -> None:
    ctx.encounter.status = "discharged"
    ctx.encounter.discharged_at = utcnow()
