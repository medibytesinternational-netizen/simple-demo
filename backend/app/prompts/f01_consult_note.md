# F1 — Ambient consultation note

Draft an OPD consultation note from the supplied transcript.

Rules:
- Use ONLY the context and transcript. Do not invent examination findings, history, or a plan.
- Every claim must cite at least one `evt_` id from the context and, where the claim comes from speech, the relevant `seg_` id.
- If a section is absent, return null and list it in `not_documented`.
- Preserve negations and laterality exactly.
- Do not change medication doses. Capture medications as `medication_mentions` only.
- Do not claim that the patient consented to recording or treatment. Consent is captured as a separate, explicit clinician action.
- Keep the note concise, in clinical English, suitable for a doctor to edit and sign.

Return JSON matching ConsultNote.
