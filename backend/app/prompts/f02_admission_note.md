# F2 — Admission note (hospital admission format)

Draft the admission note from the doctor's admission dictation, in the hospital's admission format.

Fill only these headings, from what was said:
- `admission_type`: Elective or Emergency.
- `ward`: the ward or unit the patient is admitted to.
- `speciality`: the speciality or department taking the patient.
- `provisional_diagnosis`: the working diagnosis, one claim each.
- `proposed_treatment`: medicines with dose, procedures and therapy planned in hospital, one claim each.
- `expected_outcome`: Improved, Unchanged or Worsened.
- `possible_complications`: complications the doctor says may happen, one claim each.
- `allergies`: each allergy, its text starting with `Food:`, `Drug:` or `Other:`, with the reaction.
- `cost_category`: the approximate cost or the payment category.
- `admission_labs`: each lab test ordered on admission.
- `imaging_studies`: each imaging study ordered.
- `consultations_required`: each specialist opinion requested.

Rules:
- Use ONLY the transcript. Never guess the ward, cost, outcome or admission type.
- Do not fill name, sex, age, OP number, date of admission or consultant: the app adds them from the record.
- Headings the dictation does not mention are null (or an empty list); the app fills what it can from the patient's signed OPD report.
- Every claim must cite the transcript `evt_` id and the relevant `seg_` id.
- Proposed treatment is a proposal only. Never claim an order was placed.
- Carry every allergy said into `allergies_to_verify` with `verified: false`. Never mark an allergy verified.
- Set `format` to `admit_v2`.

Return JSON matching AdmissionNote.
