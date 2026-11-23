// How a lab result is shown, derived only from what the API returns: the result's `flag`
// (set by the laboratory, the seeded record or the report reader) and its `review_status`.
// Nothing here applies clinical thresholds of its own.
import type { Lab } from "../../types";
import { parseRange } from "../../components/charts";

export type Severity = "critical" | "high" | "low" | "abnormal" | "normal" | "unknown";

/** Flags the backend treats as abnormal (the same set rule R3 raises an alert for). */
const ABNORMAL: Severity[] = ["critical", "high", "low", "abnormal"];

export function severityOf(lab: Lab): Severity {
  const flag = String(lab.flag ?? "").trim().toLowerCase();
  return (["critical", "high", "low", "abnormal", "normal"] as const).find((known) => known === flag) ?? "unknown";
}

export const isAbnormal = (lab: Lab) => ABNORMAL.includes(severityOf(lab));
/** The server writes "unreviewed"; anything else counts as reviewed, as before. */
export const isUnreviewed = (lab: Lab) => lab.review_status === "unreviewed";
/** Only results the source flagged normal can be reviewed together. Unflagged results are reviewed one by one. */
export const isBulkReviewable = (lab: Lab) => isUnreviewed(lab) && severityOf(lab) === "normal";

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  low: "Low",
  abnormal: "Abnormal",
  normal: "Normal",
  unknown: "Not flagged",
};

const RANK: Record<Severity, number> = { critical: 0, high: 1, low: 1, abnormal: 1, unknown: 2, normal: 3 };

export type LabFilter = "all" | "abnormal" | "unreviewed";

export function matchesFilter(lab: Lab, filter: LabFilter, query: string): boolean {
  if (filter === "abnormal" && !isAbnormal(lab)) return false;
  if (filter === "unreviewed" && !isUnreviewed(lab)) return false;
  const q = query.trim().toLowerCase();
  return !q || String(lab.name ?? "").toLowerCase().includes(q);
}

export type SectionKey = "needs-review" | "normal-pending" | "reviewed-abnormal" | "reviewed-other";

export type LabSection = { key: SectionKey; labs: Lab[] };

/** Groups by review status and the source's flag only; no clinical categories are invented. */
export function sectionOf(lab: Lab): SectionKey {
  if (isUnreviewed(lab)) return severityOf(lab) === "normal" ? "normal-pending" : "needs-review";
  return isAbnormal(lab) ? "reviewed-abnormal" : "reviewed-other";
}

const ORDER: SectionKey[] = ["needs-review", "normal-pending", "reviewed-abnormal", "reviewed-other"];

export function groupLabs(labs: Lab[]): LabSection[] {
  const sorted = [...labs].sort(
    (a, b) => RANK[severityOf(a)] - RANK[severityOf(b)] || String(a.name).localeCompare(String(b.name)),
  );
  return ORDER.map((key) => ({ key, labs: sorted.filter((lab) => sectionOf(lab) === key) })).filter((s) => s.labs.length);
}

// ---------------------------------------------------------------------------------------------
// Reference-range bar (docs/redesign/labs-wireframe.md, "Reference-range bar rules").
// The bar only illustrates the value against the range text the API supplied. It is drawn when
// every rule holds; otherwise the page shows the original text alone.
// ---------------------------------------------------------------------------------------------

const PLAIN_NUMBER = /^-?\d+(?:\.\d+)?$/;

/** The value as a number only when it is a plain number ("2.9", 13.8); "<0.5", "positive" give null. */
export function plainNumber(value: unknown): number | null {
  const text = typeof value === "number" ? String(value) : String(value ?? "").trim();
  if (!PLAIN_NUMBER.test(text)) return null;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Both limits of a two-sided numeric range ("0.7 - 1.3"); one-sided, free text or empty give null. */
export function twoSidedRange(text: unknown): { low: number; high: number } | null {
  const parsed = parseRange(String(text ?? ""));
  if (!parsed || parsed.low === undefined || parsed.high === undefined || !(parsed.low < parsed.high)) return null;
  return { low: parsed.low, high: parsed.high };
}

export type RangeBarModel = {
  low: number;
  high: number;
  /** Marker position on the track, 0..100. The band is 25..75; each side holds one band-width. */
  position: number;
  /** Set when the value is more than one band-width outside the range: the marker stops at the end. */
  beyond: "below" | "above" | null;
};

export function rangeBarModel(lab: Lab): RangeBarModel | null {
  const range = twoSidedRange(lab.reference_range);
  const value = plainNumber(lab.value);
  if (!range || value === null) return null;
  const severity = severityOf(lab);
  const inside = value >= range.low && value <= range.high;
  // The drawn position must agree with the API flag; on any disagreement the bar is not drawn.
  const agrees =
    severity === "normal" ? inside
      : severity === "high" ? value > range.high
        : severity === "low" ? value < range.low
          : severity === "critical" || severity === "abnormal" ? !inside
            : false; // unknown flag: no bar
  if (!agrees) return null;
  const t = (value - range.low) / (range.high - range.low); // 0..1 inside the band
  let position: number;
  let beyond: RangeBarModel["beyond"] = null;
  if (t < 0) {
    position = 25 + Math.max(t, -1) * 25;
    if (t < -1) beyond = "below";
  } else if (t > 1) {
    position = 75 + Math.min(t - 1, 1) * 25;
    if (t > 2) beyond = "above";
  } else {
    position = 25 + t * 50;
  }
  return { ...range, position, beyond };
}

// ---------------------------------------------------------------------------------------------
// History: real lab_result events from the timeline, grouped by test name. Nothing is estimated.
// ---------------------------------------------------------------------------------------------

export type LabPoint = {
  event_id: string;
  value: string | number;
  unit: string;
  flag: string;
  review_status: string;
  collected_at: string;
  source: string;
};

type TimelineEvent = { id: string; status?: string; occurred_at?: string; source_label?: string; source?: string; payload?: Record<string, any> };

const when = (value: string) => {
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : 0;
};

/** Test name (lower case) → results oldest first. Superseded events are left out. */
export function historyByTest(events: TimelineEvent[]): Map<string, LabPoint[]> {
  const byName = new Map<string, LabPoint[]>();
  for (const event of events) {
    if (event.status && event.status !== "approved") continue;
    const payload = event.payload || {};
    const name = String(payload.name ?? "").trim().toLowerCase();
    if (!name) continue;
    const point: LabPoint = {
      event_id: event.id,
      value: payload.value,
      unit: String(payload.unit ?? ""),
      flag: String(payload.flag ?? ""),
      review_status: String(payload.review_status ?? "reviewed"),
      collected_at: String(payload.collected_at || event.occurred_at || ""),
      source: String(event.source_label || event.source || ""),
    };
    byName.set(name, [...(byName.get(name) || []), point]);
  }
  for (const points of byName.values()) points.sort((a, b) => when(a.collected_at) - when(b.collected_at));
  return byName;
}

export type Comparison = {
  previous: LabPoint;
  /** Arithmetic difference current − previous, only when both are plain numbers in the same unit. */
  change: { direction: "up" | "down" | "same"; text: string } | null;
};

const decimals = (n: number) => (String(n).split(".")[1] || "").length;

/** The result just before this one for the same test, if the timeline really has one. */
export function compareWithPrevious(lab: Lab, series: LabPoint[] | undefined): Comparison | null {
  if (!series || series.length < 2) return null;
  const index = series.findIndex((point) => point.event_id === lab.event_id);
  if (index <= 0) return null;
  const previous = series[index - 1];
  const now = plainNumber(lab.value);
  const before = plainNumber(previous.value);
  const sameUnit = String(lab.unit ?? "").trim().toLowerCase() === previous.unit.trim().toLowerCase();
  if (now === null || before === null || !sameUnit) return { previous, change: null };
  const places = Math.max(decimals(now), decimals(before));
  const diff = Number((now - before).toFixed(places));
  if (diff === 0) return { previous, change: { direction: "same", text: "no change" } };
  return { previous, change: { direction: diff > 0 ? "up" : "down", text: `${diff > 0 ? "+" : "−"}${Math.abs(diff).toFixed(places)}` } };
}

/** Latest collection time across the results, for the page header. */
export function lastCollected(labs: Lab[]): string {
  let best = "";
  for (const lab of labs) if (lab.collected_at && when(lab.collected_at) >= when(best)) best = lab.collected_at;
  return best;
}

/** "19 Oct 2026, 06:00" for a timestamp, "21 Oct 2026" for a date; the raw text if it cannot be read. */
export function formatCollected(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const hasTime = /T\d{2}:\d{2}/.test(value);
  return date.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    // A bare date is parsed as UTC midnight; show it as that same calendar day everywhere.
    ...(hasTime ? { hour: "2-digit", minute: "2-digit" } : { timeZone: "UTC" }),
  });
}
