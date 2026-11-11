import type {
  Color,
  DischargeSection,
  FactStatus,
  JobStatus,
  StageName,
  StageState,
} from "../api/types";

export const PIPELINE_LINE = "MedASR → small-int8 second pass → fuzzy matcher → gpt-4.1";

export const STAGE_LABELS: Record<StageName, string> = {
  preprocess: "Preprocess",
  medasr: "MedASR",
  second_pass: "Second pass",
  extract: "Fuzzy match",
  llm_review: "gpt-4.1 review",
  verify: "Verify",
  discharge: "Discharge note",
};

export const STAGE_ORDER: readonly StageName[] = [
  "preprocess",
  "medasr",
  "second_pass",
  "extract",
  "llm_review",
  "verify",
  "discharge",
];

/** One-line explanation of each stage, shown while it has no live detail. */
export const STAGE_HINTS: Record<StageName, string> = {
  preprocess: "Decode, mono 16 kHz, level-normalise, silence check",
  medasr: "google/medasr speech recognition",
  second_pass: "small-int8 re-listen for missed drugs and vitals",
  extract: "Regex extraction and fuzzy drug-name matching",
  llm_review: "Term validation and context repair from a closed shortlist",
  verify: "Deterministic fact verification",
  discharge: "Six sections, every item gated against the transcript",
};

export const STAGE_STATE_LABELS: Record<StageState, string> = {
  pending: "Pending",
  running: "Running",
  done: "Done",
  degraded: "Degraded",
  failed: "Failed",
};

export const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  queued: "Queued",
  running: "Processing",
  succeeded: "Done",
  failed: "Failed",
};

export const SECTION_TITLES: Record<DischargeSection, string> = {
  present_illness: "Present illness",
  examination_findings: "Examination findings",
  previous_diagnosis: "Previous diagnosis",
  plan_of_management: "Plan of management",
  diet_instructions: "Diet instructions",
  general_instructions: "General instructions",
};

export const COLOR_MEANINGS: Record<Color, string> = {
  GREEN: "Confident match",
  YELLOW: "Check before signing",
  RED: "Physician must confirm",
};

export const FACT_STATUS_LABELS: Record<FactStatus, string> = {
  verified: "Verified",
  needs_review: "Needs review",
  rejected: "Rejected",
};

/** 0.734 → "0.7 s"; 75.2 → "1 min 15 s"; null → "". */
export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return "";
  if (seconds < 10) return `${seconds.toFixed(1)} s`;
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds - m * 60);
  return s === 0 ? `${m} min` : `${m} min ${s} s`;
}

/** Audio clock: 66.8 → "1:07". */
export function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** 0.87 → "87%". */
export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  return `${Math.round(value * 100)}%`;
}

export function formatDose(dose: number | null, unit: string | null): string {
  if (dose === null) return "";
  const n = Number.isInteger(dose) ? String(dose) : String(Number(dose.toFixed(3)));
  return unit ? `${n} ${unit}` : n;
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDb(value: number | null): string {
  return value === null || !Number.isFinite(value) ? "" : `${value.toFixed(1)} dB`;
}

export function capitalize(text: string): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}
