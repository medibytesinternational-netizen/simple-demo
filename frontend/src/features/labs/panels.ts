import type { Lab } from "../../types";
import type { Tone } from "../../components/ui";

/**
 * Display grouping only. The lab feed carries no panel field, so related tests are
 * grouped by name. Anything not listed falls into "Other tests".
 */
const PANELS: { name: string; tests: string[] }[] = [
  { name: "Renal", tests: ["creatinine", "egfr", "urea", "bun", "potassium", "sodium", "chloride", "bicarbonate", "uric acid"] },
  { name: "Diabetic", tests: ["hba1c", "glucose", "fasting glucose", "random glucose", "fasting blood sugar", "random blood sugar"] },
  { name: "Infection & inflammation", tests: ["crp", "c-reactive protein", "white cell count", "wbc", "procalcitonin", "esr"] },
  { name: "Haematology", tests: ["haemoglobin", "hemoglobin", "hb", "platelets", "platelet count", "inr"] },
  { name: "Liver", tests: ["alt", "ast", "bilirubin", "alp", "albumin", "ggt"] },
];
export const OTHER_PANEL = "Other tests";
const PANEL_ORDER = [...PANELS.map((p) => p.name), OTHER_PANEL];

export function panelOf(name: string): string {
  const key = name.trim().toLowerCase();
  return PANELS.find((p) => p.tests.includes(key))?.name ?? OTHER_PANEL;
}

export function groupByPanel(labs: Lab[]): { panel: string; labs: Lab[] }[] {
  const groups = new Map<string, Lab[]>();
  for (const lab of labs) {
    const panel = panelOf(lab.name);
    groups.set(panel, [...(groups.get(panel) || []), lab]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => PANEL_ORDER.indexOf(a) - PANEL_ORDER.indexOf(b))
    .map(([panel, items]) => ({ panel, labs: items }));
}

/** Flags the backend treats as abnormal (rules.py R3). */
const ABNORMAL = new Set(["critical", "high", "low", "abnormal"]);

export type Severity = { key: string; label: string; tone: Tone; rank: number };

export function severityOf(flag: string | undefined): Severity {
  const value = String(flag || "").trim().toLowerCase();
  if (value === "critical") return { key: value, label: "Critical", tone: "critical", rank: 0 };
  if (value === "high") return { key: value, label: "High", tone: "warning", rank: 1 };
  if (value === "low") return { key: value, label: "Low", tone: "warning", rank: 1 };
  if (value === "abnormal") return { key: value, label: "Abnormal", tone: "warning", rank: 2 };
  if (value === "normal") return { key: value, label: "Normal", tone: "success", rank: 3 };
  return { key: "unknown", label: "Not flagged", tone: "neutral", rank: 4 };
}

export const isAbnormal = (lab: Lab) => ABNORMAL.has(String(lab.flag || "").trim().toLowerCase());
export const isUnreviewed = (lab: Lab) => lab.review_status === "unreviewed";

/** A reference range worth showing, or null when the source did not report one. */
export function referenceText(range: string | undefined | null): string | null {
  const text = String(range ?? "").trim();
  return text && text !== "—" && text !== "-" && text.toLowerCase() !== "unknown" ? text : null;
}

export function numeric(value: unknown): number | null {
  const n = typeof value === "number" ? value : parseFloat(String(value ?? "").replace(/^[<>]=?\s*/, ""));
  return Number.isFinite(n) ? n : null;
}
