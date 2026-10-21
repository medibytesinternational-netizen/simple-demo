export const READING_CATEGORIES = [
  { value: "vitals", label: "Vital signs" },
  { value: "ventilator", label: "Ventilator" },
  { value: "infusion", label: "Infusion" },
  { value: "intake_output", label: "Intake and output" },
  { value: "neuro", label: "Neuro" },
  { value: "lines", label: "Lines and drains" },
  { value: "skin", label: "Skin" },
  { value: "medication", label: "Medication" },
] as const;

export type ReadingCategory = (typeof READING_CATEGORIES)[number]["value"];

export type ReadingBody = {
  category: ReadingCategory;
  label: string;
  value: string;
  unit: string;
  device: string;
  recorded_at: string;
  encounter_id?: string;
};

export type ReadingResult = {
  duplicate: boolean;
  source_event_id: string;
  chart?: "icu" | "ward";
  encounter_id?: string;
};

/** A number needs a unit; the server refuses it otherwise. */
export function needsUnit(value: string): boolean {
  const text = value.trim();
  return text !== "" && !Number.isNaN(Number(text));
}

export function readingOk(body: Pick<ReadingBody, "label" | "value" | "unit" | "recorded_at">): boolean {
  return (
    body.label.trim() !== "" &&
    body.value.trim() !== "" &&
    body.recorded_at !== "" &&
    (!needsUnit(body.value) || body.unit.trim() !== "")
  );
}
