# F2 — Admission assessment

Draft an inpatient admission assessment (H&P) from the referral/interview transcript and the patient's existing record.

Rules:
- Use ONLY supplied context and transcript. Cite `evt_` and `seg_` ids for every claim.
- If the transcript contains an examination description (for example "on examination", a body part, vital signs, or a negative finding), populate `exam.general` from it. Only leave `exam` null and add "Examination" to `not_documented` when no examination is described anywhere.
- Proposed orders are proposals only. Each item must use the keys `order`, `rationale` and `source_event_ids`. Never claim an order was placed.
- Carry every known allergy into `allergies_to_verify` with `verified: false` and its source. Never mark an allergy verified; that is an explicit clinician action.
- Reconcile the admission diagnosis against documented problems, but do not add a new diagnosis that is not supported by the transcript.
- Keep it concise and clinically neutral.

Return JSON matching AdmissionNote.
