# F12 — Claim pack gap explanation

Explain the deterministic claim-readiness gaps.

Rules:
- The missing-document, underbilled-item, contradiction and TPA-review lists are computed in code. Do not add or remove gaps.
- Treat every contradiction as blocking until a human resolves it. Never explain it away or imply the claim can be submitted with it.
- Cite evidence event ids for every gap.
- Never state or imply that a claim will be submitted or paid. Do not use "claim submission", "submit the claim", "payer approval" or "reimbursement".
- Describe blockers as "clinical review readiness", not submission readiness.
- The output is a review queue item for a human.
- Keep the explanation factual: what is missing, why it blocks review, and what to do next.

Return JSON matching ClaimGapExplanation.
