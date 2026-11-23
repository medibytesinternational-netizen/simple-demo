// Revenue leakage figures, derived only from GET /revenue/leakage (and the encounter from /meta).
// The backend total `leakage_amount` is shown as returned; every other amount here is a plain sum
// of the same findings' fields, so it can be checked against that total. Nothing is estimated
// beyond what the backend already computed, and a missing value stays missing (null), never 0.
import type { Encounter, Leakage } from "../../types";

export type Finding = Leakage["findings"][number];

/** Root causes, from the API's `kind` (live) or `billing_status` (older DEMO data without `kind`). */
export type Cause = "not_billed" | "below_tariff" | "qty_short" | "qty_over" | "unsupported" | "below_or_qty";

export function causeOf(f: Finding): Cause {
  if (f.kind === "unbilled") return "not_billed";
  if (f.kind === "underbilled") return "below_tariff";
  if (f.kind === "quantity_mismatch") return f.billing_status === "underbilled" ? "qty_short" : "qty_over";
  if (f.kind === "unsupported") return "unsupported";
  // No `kind` (DEMO fixture): billing_status alone cannot separate below-tariff from short quantity.
  if (f.billing_status === "unbilled") return "not_billed";
  if (f.billing_status === "unsupported") return "unsupported";
  return "below_or_qty";
}

export const CAUSE_LABEL: Record<Cause, string> = {
  not_billed: "Not billed",
  below_tariff: "Below tariff",
  qty_short: "Quantity mismatch · fewer billed",
  qty_over: "Quantity mismatch · more billed than documented",
  unsupported: "Billed without documentation",
  below_or_qty: "Below tariff or short quantity",
};

/** Root-cause cards. Quantity mismatch groups both directions; only the "fewer billed" side is revenue at risk. */
export type CauseCard = "not_billed" | "below_tariff" | "quantity" | "unsupported" | "below_or_qty";
export function cardOf(cause: Cause): CauseCard {
  return cause === "qty_short" || cause === "qty_over" ? "quantity" : cause;
}

export const SERVICE_LABEL: Record<string, string> = {
  procedure: "Procedures",
  medication: "Medications",
  investigation: "Investigations",
  consult: "Consultations",
  bed_day: "Bed-days",
};

export const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);

/** Mirrors the backend's leakage_amount: unbilled and underbilled findings with a variance. */
export const inTotal = (f: Finding) => (f.billing_status === "unbilled" || f.billing_status === "underbilled") && num(f.variance) !== null && (f.variance as number) !== 0;

/**
 * Open-admission estimate: bed-days on an encounter without a discharge time. The backend counts
 * them up to the current clock, so the figure is a calculated estimate, not a confirmed discrepancy.
 * Null when the encounter is not known (the page then says so rather than guessing).
 */
export function isEstimate(f: Finding, encounter: Encounter | undefined): boolean | null {
  if (f.service_kind !== "bed_day") return false;
  if (!encounter) return null;
  return !encounter.discharged_at;
}

export const sum = (values: (number | null)[]) => values.reduce<number>((total, v) => total + (v ?? 0), 0);

export type Totals = {
  /** API leakage_amount, or null when the data does not include it (DEMO). */
  total: number | null;
  /** Σ variance of in-total findings that are open-admission estimates. */
  estimate: number;
  /** total − estimate (null without a total). */
  discrepancies: number | null;
  /** Σ variance of in-total findings, to check against `total`. */
  breakdown: number;
  /** True when the breakdown does not reproduce the API total. */
  mismatch: boolean;
  /** Σ billed_amount of findings billed without documentation (not part of the total). */
  unsupportedBilled: number | null;
  /** Some amounts are missing from the data. */
  amountsMissing: boolean;
};

export function totals(data: Leakage | undefined, encounter: Encounter | undefined): Totals {
  const findings = data?.findings ?? [];
  const total = num(data?.leakage_amount);
  const counted = findings.filter(inTotal);
  const estimate = sum(counted.filter((f) => isEstimate(f, encounter) === true).map((f) => num(f.variance)));
  const breakdown = sum(counted.map((f) => num(f.variance)));
  const unsupported = findings.filter((f) => causeOf(f) === "unsupported");
  const unsupportedAmounts = unsupported.map((f) => num(f.billed_amount));
  return {
    total,
    estimate,
    discrepancies: total === null ? null : total - estimate,
    breakdown,
    mismatch: total !== null && Math.abs(breakdown - total) > 0.5,
    unsupportedBilled: unsupported.length && unsupportedAmounts.every((v) => v !== null) ? sum(unsupportedAmounts) : null,
    amountsMissing: findings.some((f) => num(f.variance) === null && f.billing_status !== "unsupported") || total === null,
  };
}

/**
 * Confirmed discrepancies by gap (largest first), then open-admission estimates, then revenue
 * findings whose amounts are missing (e.g. DEMO data), then compliance findings (billed without
 * documentation, over-billed quantities) last.
 */
export function prioritise(findings: Finding[], encounter: Encounter | undefined): Finding[] {
  const compliance = (f: Finding) => f.billing_status === "unsupported";
  const tier = (f: Finding) => (inTotal(f) ? (isEstimate(f, encounter) === true ? 1 : 0) : compliance(f) ? 3 : 2);
  return [...findings].sort((a, b) => tier(a) - tier(b) || (num(b.variance) ?? -1) - (num(a.variance) ?? -1) || String(a.procedure).localeCompare(String(b.procedure)));
}

/** Gap per service type, only when every counted finding has a service type and a variance. */
export function byService(findings: Finding[], encounter: Encounter | undefined) {
  const counted = findings.filter(inTotal);
  if (!counted.length || counted.some((f) => !f.service_kind || num(f.variance) === null)) return null;
  const groups = new Map<string, { kind: string; amount: number; count: number; estimate: boolean }>();
  for (const f of counted) {
    const kind = String(f.service_kind);
    const row = groups.get(kind) || { kind, amount: 0, count: 0, estimate: false };
    row.amount += num(f.variance) ?? 0;
    row.count += 1;
    row.estimate = row.estimate || isEstimate(f, encounter) === true;
    groups.set(kind, row);
  }
  return [...groups.values()].sort((a, b) => b.amount - a.amount);
}

// --- CSV (built in the browser from the loaded findings; missing values are left blank) ---------

const cell = (value: unknown) => {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

export function findingsCsv(findings: Finding[], encounter: Encounter | undefined): string {
  const header = ["category", "estimate_open_admission", "service", "code", "service_type", "documented_quantity", "billed_quantity", "unit_price", "expected_amount", "billed_amount", "gap", "counted_in_total", "explanation", "evidence_event_ids"];
  const rows = findings.map((f) => [
    CAUSE_LABEL[causeOf(f)],
    isEstimate(f, encounter) === null ? "" : isEstimate(f, encounter) ? "yes" : "no",
    f.procedure, f.code, f.service_kind, f.documented_quantity, f.billed_quantity, f.unit_price,
    f.expected_amount, f.billed_amount, f.variance, inTotal(f) ? "yes" : "no", f.explanation,
    (f.evidence_event_ids || []).join(" "),
  ]);
  return [header, ...rows].map((row) => row.map(cell).join(",")).join("\r\n");
}
