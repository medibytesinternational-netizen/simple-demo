/** The hospital admission note format, in its order. Record headings come from registration and the visit. */
export const ADMIT_HEADER_FIELDS: [string, string][] = [
  ["name", "Name"],
  ["sex", "Sex"],
  ["age", "Age"],
  ["op_number", "OP number"],
  ["date_of_admission", "On (date of admission)"],
  ["consultant", "Under (consultant)"],
];

/** [key, label, holds a list] */
export const ADMIT_HEARD_SECTIONS: [string, string, boolean][] = [
  ["admission_type", "Elective or emergency", false],
  ["ward", "Admit to ward", false],
  ["speciality", "Speciality", false],
  ["provisional_diagnosis", "Provisional diagnosis", true],
  ["proposed_treatment", "Proposed treatment", true],
  ["expected_outcome", "Expected outcome (improved, unchanged or worsened)", false],
  ["possible_complications", "Possible complications", true],
  ["allergies", "Allergies", true],
  ["cost_category", "Approximate cost or category", false],
  ["admission_labs", "Admission labs", true],
  ["imaging_studies", "Imaging studies", true],
  ["consultations_required", "Consultations required", true],
];

export const isAdmitV2 = (content: any) => content?.format === "admit_v2";
