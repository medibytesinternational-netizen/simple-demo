# F7 — ICU flow sheet

Assemble a structured ICU flow-sheet draft from device readings and structured observations.

Rules:
- Every entry must come from the context. Never invent, estimate, round or back-fill a value.
- Preserve the unit and recorded timestamp exactly as supplied.
- Cite the source `evt_` id for every entry.
- Group entries by category: vitals, ventilator, infusion, intake_output, neuro, lines, skin, other.
- Do not diagnose or recommend treatment. This is a chart assembly task, not a clinical decision.
- Write a short `summary` that states what was assembled and the shift window. Do not add a clinical interpretation.
- If a chart section is absent, list it in `not_documented` rather than producing an empty or guessed value.

Return JSON matching ICUFlowSheet.
