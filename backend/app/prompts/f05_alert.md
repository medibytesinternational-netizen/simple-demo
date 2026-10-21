# F5 — Alert copy

Phrase a clinical alert that has already been decided by a deterministic rule.

Rules:
- The rule, severity, and evidence are fixed. Do not add a new alert or change severity.
- Explain what fired, why it matters, and the next review action in plain clinical language.
- Cite the supplied evidence event ids.
- Never imply the system has taken an action. The clinician decides.

Return JSON matching AlertCopy.
