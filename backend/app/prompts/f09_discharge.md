# F9 — Discharge summary

Draft a discharge summary for the encounter.

Rules:
- Synthesize ONLY approved timeline events supplied in context. Cite `evt_` ids for every paragraph.
- Cover admission diagnosis, hospital course, procedures, discharge medications, follow-up, pending results, and red flags.
- The medication list is assembled by deterministic code. Do not invent, add, or stop medications.
- Do not state that a pending result is normal. Mark pending results as pending.
- If a section has no supporting event, leave it out rather than inventing it.
- Only include follow-up if an approved timeline event explicitly documents it. A proposed task is not a documented plan.
- The clinician will review, edit, and sign; do not claim the summary is final.

Return JSON matching DischargeSummary.
