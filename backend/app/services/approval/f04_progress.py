from __future__ import annotations

from . import ApprovalContext, validator


@validator("F4")
def require_exam_and_plan(ctx: ApprovalContext) -> None:
    payload = ctx.payload
    exam = (payload.get("exam") or {}).get("general") or {}
    plan = payload.get("plan") or {}
    if not str(exam.get("text", "")).strip() or not str(plan.get("text", "")).strip():
        raise ValueError(
            "F4 cannot be approved: the examination and plan are required. "
            "Edit the draft to document them first."
        )
