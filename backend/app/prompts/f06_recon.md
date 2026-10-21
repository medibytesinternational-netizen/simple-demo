# F6 — Medication reconciliation explanation

Explain the deterministic differences between the home medication list and the current inpatient plan.

Rules:
- The discrepancy list is computed in code. Do not add or remove discrepancies.
- Explain each discrepancy in one or two sentences, citing event ids.
- Do not recommend a specific dose change. Flag the issue for clinician review.
- Preserve the distinction between "omitted", "dose changed", "duplicate", "interaction", "allergy", and "contraindicated".

Return JSON matching ReconExplanation.
