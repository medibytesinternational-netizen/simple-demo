# F4 — Daily progress note

Draft a daily progress note from the supplied overnight events and clinician input.

Rules:
- Use ONLY the context and transcript. Cite `evt_` and `seg_` ids.
- If no examination is documented, leave `exam` fields null and add "Examination" to `not_documented`.
- If no plan is documented, leave `plan` null and add "Plan" to `not_documented`.
- This module must visibly refuse to invent an examination or plan. Do not fill gaps with generic text.
- Do not change medication doses or order new tests.

Return JSON matching ProgressNote.
