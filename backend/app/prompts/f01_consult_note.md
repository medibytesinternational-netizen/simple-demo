# F1 — Ambient consultation note (hospital OPD format)

Draft an OPD consultation note from the supplied transcript, in the hospital's OPD format.

Fill only these headings, from what was said:
- `mode_of_admission`: how the patient came (walked in, brought by family, ambulance, referred, from emergency).
- `referring_physician`: the doctor or hospital who referred the patient, as named.
- `previous_admission`: earlier hospital admissions (where, when, why).
- `previous_diagnosis`: conditions diagnosed before this visit, one claim each.
- `allergies`: each allergy, its text starting with `Food:`, `Drug:` or `Other:` and the reaction; "No known allergies" if the patient says so.
- `pain`: site, duration, score out of 10, frequency and radiation, only the parts that were said.
- `occupation`: the patient's work.
- `source_of_history`: who gave the history and how reliable it is.
- `chief_complaints`: the reasons for today's visit with their duration, one claim each.
- `history_of_present_illness`: the story of the current illness (onset, course, triggers, associated and denied symptoms).

Rules:
- Use ONLY the transcript. Never guess the mode of admission, the source of history or the occupation.
- Do not fill the patient's name, age, sex, hospital number, department, consultant or the recording doctor: the app adds them from registration.
- Examination, medicines, tests and plans are not part of this format: leave them out.
- Every claim must cite at least one `evt_` id from the context and the relevant `seg_` id.
- A heading nobody spoke about is null (or an empty list) and is listed by its label in `not_documented`.
- Preserve negations and laterality exactly.
- Do not claim that the patient consented to recording or treatment. Consent is a separate clinician action.
- Set `format` to `opd_v2`.

Return JSON matching ConsultNote.
