// API contract between the MediBytes FastAPI server (medibytes/api) and this UI.
// The server's pydantic models mirror these shapes; keep the two in step.

export type Color = "GREEN" | "YELLOW" | "RED";

export type StageName =
  | "preprocess"
  | "medasr"
  | "second_pass"
  | "extract"
  | "llm_review"
  | "verify"
  | "discharge";

export type StageState = "pending" | "running" | "done" | "degraded" | "failed";

export interface StageStatus {
  name: StageName;
  label: string; // e.g. "MedASR", "gpt-4.1 review"
  state: StageState;
  seconds: number | null;
  detail: string; // short human note, e.g. "2 LLM calls" or an error message
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface JobSummary {
  job_id: string;
  filename: string;
  status: JobStatus;
  created_at: string; // ISO 8601
}

export interface Job extends JobSummary {
  error: string | null;
  stages: StageStatus[]; // always all 7, in pipeline order
  result: JobResult | null; // present when status === "succeeded"
}

export interface JobResult {
  audio: AudioMeta;
  transcript: Transcript;
  entities: Entities;
  verify: Verify;
  discharge: DischargeNote;
  files: string[]; // names usable with GET /api/jobs/{id}/files/{name}
}

export interface AudioMeta {
  duration_s: number;
  sample_rate: number;
  vad_ratio: number | null;
  snr_db: number | null;
  rms_dbfs_before: number | null;
  rms_dbfs_after: number | null;
  input_sha256: string;
}

export interface Segment {
  id: number;
  start?: number;
  end?: number;
  text: string;
}

export interface Transcript {
  text: string;
  normalized_en: string;
  language: string;
  segments: Segment[];
  stt_engine: string; // "medasr:google/medasr@cpu"
}

export type SpanStatus = "exact" | "ambiguous" | "not_found";

export interface Spanned {
  start_char: number; // -1 unless span_status === "exact"; offsets into transcript.normalized_en
  end_char: number;
  span_status: SpanStatus;
}

export interface ReferenceBlock {
  kind: "substance" | "brand";
  name: string;
  substances: string[];
  units: string[];
  mass_mg?: [number, number] | null;
}

export interface Candidate {
  name: string;
  score: number;
  matched_alias?: string;
  source?: "mini" | "reference";
  dose_implausible?: boolean;
  reference?: ReferenceBlock;
}

// gpt-4.1 term-validation verdict for one fuzzy-matched drug row.
// corrected: a shortlist name replaced the heard word (RED if it overrules the matcher)
// ambiguous: sent to a human (RED); rejected: no candidate fits (RED, name reverts to heard word)
// skipped: the LLM could not be consulted; the matcher's answer stands
export interface Validation {
  status: "corrected" | "ambiguous" | "rejected" | "skipped";
  reason: string;
  original_sentence?: string;
  final_output_sentence?: string;
  applied_corrections?: { replaced_token: string; substituted_with: string }[];
  semantic_confidence_score?: number;
  engine?: string; // "llm:gpt-4.1"
  overrules_matcher?: boolean;
  unit_filtered?: string[];
}

// Present on a drug row that gpt-4.1 context repair added (always RED).
export interface RowContextRepair {
  heard: string;
  model: string;
  shortlist: [string, number][]; // [name, spelling score]
}

export interface DrugRow extends Spanned {
  name: string;
  dose: number | null;
  unit: "mg" | "mcg" | "g" | "ml" | "U" | null;
  frequency: string;
  duration: string;
  confidence: number;
  color: Color;
  source_sentence: string;
  negated: boolean;
  allergen?: boolean;
  note?: string;
  raw_token?: string; // the word actually heard
  matcher_pick?: string; // fuzzy matcher's own pick
  candidates?: Candidate[]; // shortlist shown to gpt-4.1
  reference?: ReferenceBlock;
  validation?: Validation; // gpt-4.1 term-validation decision
  second_pass?: string; // set when only the small-int8 second pass heard it
  context_repair?: RowContextRepair; // set when gpt-4.1 context repair added this row
}

export interface TextRow extends Spanned {
  text: string;
  confidence: number;
  color: Color;
  source_sentence: string;
  negated?: boolean;
  note?: string;
}

export interface RepairDecision {
  heard: string;
  shortlist: [string, number][];
  confidence: number;
  reason: string;
  chosen?: string;
}

export interface RepairAttempt {
  heard: string;
  sentence: string;
  shortlist: [string, number][];
  outcome?: "repaired" | "none" | "duplicate" | "error";
  chosen?: string | null;
  confidence?: number;
}

// Clip-level log of the gpt-4.1 context-repair stage.
export interface ContextRepair {
  status: "ran" | "skipped";
  reason?: string;
  engine?: string;
  considered?: number;
  calls?: number;
  llm_seconds?: number;
  repaired?: RepairDecision[];
  declined?: RepairDecision[];
  errors?: string[];
  attempts?: RepairAttempt[];
}

export interface Entities {
  drugs: DrugRow[];
  symptoms: TextRow[];
  vitals: TextRow[];
  allergies: TextRow[];
  diagnosis: Partial<TextRow>; // {} when none
  followup: Partial<TextRow>; // {} when none
  term_validator?: string;
  context_repair?: ContextRepair;
  drug_second_pass?: Record<string, number>;
}

export type FactStatus = "verified" | "needs_review" | "rejected";

export interface VerifyFact {
  kind: "drug" | "vital" | "symptom" | "allergy" | "diagnosis" | "followup";
  name?: string;
  text?: string;
  dose?: number | null;
  unit?: string | null;
  negated?: boolean;
  status: FactStatus;
  checks: string[];
  notes: string;
  confidence: number;
  source_sentence: string;
}

export interface Verify {
  facts: VerifyFact[];
  summary: Record<string, unknown>;
  brand_mentions?: { brand: string; number: string; substances: string[] }[];
}

export const DISCHARGE_SECTIONS = [
  "present_illness",
  "examination_findings",
  "previous_diagnosis",
  "plan_of_management",
  "diet_instructions",
  "general_instructions",
] as const;

export type DischargeSection = (typeof DISCHARGE_SECTIONS)[number];

export interface DischargeItem {
  text: string;
  source_sentence: string;
  seg_id?: number | null;
  confidence?: number;
  verified_kind?: string;
  verified_status?: FactStatus;
}

export interface DischargeNote {
  sections: Record<DischargeSection, { items: DischargeItem[] }>;
  provenance: {
    llm_engine?: string;
    verified_summary?: Record<string, unknown>;
    dropped_unproven?: number;
    prefilled?: number;
    schema?: "valid" | "INVALID";
    schema_error?: string;
    /** What was dictated (gpt-4.1 analysis, or keyword cues) against what the note holds. */
    coverage?: {
      source?: "analysis" | "cues";
      dictated?: Partial<Record<DischargeSection, number>>;
      /** Sections with dictated parts but no item. */
      missing: DischargeSection[];
      /** Dictated parts no item came from, by section. */
      unused?: Partial<Record<DischargeSection, string[]>>;
      retry?: { sections: DischargeSection[]; parts?: number; added?: number; dropped?: number; error?: string };
    };
  };
}

export interface Health {
  status: "ok";
  pipeline: string; // "MedASR → small-int8 second pass → fuzzy matcher → gpt-4.1"
  llm: { model: string; configured: boolean };
  jobs: Partial<Record<JobStatus, number>>;
}

export interface JobAccepted {
  job_id: string;
  status: JobStatus;
  status_url: string;
}
