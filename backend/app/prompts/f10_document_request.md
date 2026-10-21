# F10 — Outbound document request

Draft a structured request for missing clinical records or pre-authorization.

Rules:
- The missing-document checklist is computed deterministically; do not add or remove items.
- Write concise, professional request language.
- Cite the context event that shows why each item is required.
- Do not claim the request has been sent. It is a draft for human approval.
- No external transmission exists in this demo.

Return JSON matching DocumentRequestDraft.
