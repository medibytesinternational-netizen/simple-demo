import type { DocumentDetail, OcrField } from "../../types";

export type DocType = "lab_report" | "discharge_summary" | "prescription" | "radiology_report";

export const DOC_TYPE_OPTIONS: { value: DocType; label: string }[] = [
  { value: "lab_report", label: "Lab report" },
  { value: "prescription", label: "Prescription" },
  { value: "radiology_report", label: "Radiology report" },
  { value: "discharge_summary", label: "Discharge summary" },
];

export function docTypeLabel(value: string): string {
  return DOC_TYPE_OPTIONS.find((item) => item.value === value)?.label ?? value.replaceAll("_", " ");
}

/** A field the reader found or a person typed. `manual` is set for typed values. */
export type F08Field = OcrField & { manual?: boolean };

export type F08Document = Omit<DocumentDetail, "extracted"> & {
  extracted: { document_type?: string; fields: F08Field[]; raw_text?: string };
};

export type ManualFieldInput = {
  name: string;
  value: string;
  unit: string;
  reference_range: string;
  collected_at: string;
};

/** Who the server records as the author when a clean lab report is saved by the upload itself. */
export const AUTO_ACTOR = "system (auto)";

/** The upload response: the document plus what the automatic save of a clean lab report did. */
export type UploadResult = DocumentDetail & {
  auto_committed: boolean;
  auto_commit_error: string | null;
  labs: unknown[];
  events: unknown[];
  new_alerts: { id: string; rule_id: string; title: string }[];
};

export type CommitResult = {
  document: DocumentDetail;
  labs: unknown[];
  events: unknown[];
  new_alerts: { id: string; rule_id: string; title: string }[];
};

/** What a committed document of this type adds to the timeline, in plain words. */
export function commitSummary(docType: string, count: number): string {
  if (docType === "prescription") return `${count} medicine${count === 1 ? "" : "s"} added to the home medicines`;
  if (docType === "radiology_report" || docType === "discharge_summary") return "One review note added to the timeline";
  return `${count} result${count === 1 ? "" : "s"} added to the timeline`;
}
