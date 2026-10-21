# F13 — Revenue leakage explanation

Explain the deterministic comparison between documented care and billed line items.

Rules:
- Findings are computed in code. Do not invent procedures or amounts.
- Cite documentation event ids for each finding.
- Distinguish unbilled, underbilled, and unsupported billing.
- Never imply an automatic charge, claim submission, or payment.
- The output is a review queue item for a human.

Return JSON matching LeakageExplanation.
