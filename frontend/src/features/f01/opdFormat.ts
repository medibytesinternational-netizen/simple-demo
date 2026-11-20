/** The hospital OPD note format, in its order. Record headings come from registration; heard ones from the consultation. */
export const OPD_HEADER_FIELDS: [string, string][] = [
  ["patient_name", "Patient name"],
  ["age_sex", "Age and sex"],
  ["date_of_admission", "Date of admission"],
  ["hospital_number", "Hospital number"],
  ["department", "Department"],
  ["unit_consultant", "Unit and consultant"],
  ["recorded_by", "History and physical recorded by"],
];

/** [key, label, holds a list] */
export const OPD_HEARD_SECTIONS: [string, string, boolean][] = [
  ["mode_of_admission", "Mode of admission", false],
  ["referring_physician", "Referring physician", false],
  ["previous_admission", "Previous admission", false],
  ["previous_diagnosis", "Previous diagnosis", true],
  ["allergies", "Allergies (food, drugs, other)", true],
  ["pain", "Pain (site, duration, score, frequency, referral or radiation)", false],
  ["occupation", "Occupation", false],
  ["source_of_history", "Source of history and reliability", false],
  ["chief_complaints", "Chief complaints", true],
  ["history_of_present_illness", "History of present illness", false],
];

export const isOpdV2 = (content: any) => content?.format === "opd_v2";
