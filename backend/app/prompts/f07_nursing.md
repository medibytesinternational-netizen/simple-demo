# F7 — Nursing shift summary

Summarize the shift from structured vitals, medication administration, and nursing events.

Rules:
- Every numeric value must come from the context; never estimate or round silently.
- Cite the source `evt_` id for each claim.
- Do not diagnose. Report observations and concerns only.
- If intake/output or a medication administration record is absent, list it in `not_documented`.

Return JSON matching ShiftSummary.
