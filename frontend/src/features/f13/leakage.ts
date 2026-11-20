import type { LeakageFinding } from "../../types";

/** Department a finding belongs to, from the tariff kind the backend attaches. */
export const DEPARTMENTS: Record<string, string> = {
  investigation: "Lab & imaging",
  medication: "Pharmacy",
  bed_day: "Ward / ICU",
  procedure: "Procedures",
  consult: "Consults",
};
export const OTHER_DEPARTMENT = "Other";
export const departmentOf = (f: LeakageFinding) => DEPARTMENTS[f.service_kind || ""] ?? OTHER_DEPARTMENT;

/** Revenue that can be recovered: documented care missing from the bill or billed short. */
export const isRecoverable = (f: LeakageFinding) => f.billing_status === "unbilled" || f.billing_status === "underbilled";

export const gapAmount = (f: LeakageFinding): number | null => (typeof f.variance === "number" ? f.variance : null);

const UNBILLED_CAUSE: Record<string, string> = {
  investigation: "Ordered, not billed",
  medication: "Given, not billed",
  procedure: "Performed, not billed",
  consult: "Consult documented, not billed",
  bed_day: "Stay documented, not billed",
};

/** Plain-language root cause, from the finding kind the backend computed. */
export function causeOf(f: LeakageFinding): string {
  const kind = f.kind || f.billing_status;
  if (kind === "unbilled") return UNBILLED_CAUSE[f.service_kind || ""] ?? "Documented, not billed";
  if (kind === "quantity_mismatch") {
    const qty = f.documented_quantity != null && f.billed_quantity != null ? ` (${f.documented_quantity} documented, ${f.billed_quantity} billed)` : "";
    return `${f.billing_status === "underbilled" ? "Quantity under-billed" : "Quantity over-billed"}${qty}`;
  }
  if (kind === "underbilled") return "Billed below tariff";
  return "Billed without documentation";
}

export function inr(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `INR ${Number(value).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function cell(value: unknown): string {
  const text = value == null ? "" : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** CSV of the findings as loaded, for billing audit. Built in the browser; nothing is sent. */
export function downloadLeakageCsv(findings: LeakageFinding[], patientId: string) {
  const header = ["Item", "Code", "Department", "Cause", "Billing status", "Documented qty", "Billed qty", "Billed amount (INR)", "Expected amount (INR)", "Gap (INR)", "Explanation", "Evidence event ids"];
  const rows = findings.map((f) => [
    f.procedure, f.code, departmentOf(f), causeOf(f), f.billing_status, f.documented_quantity, f.billed_quantity,
    f.billed_amount, f.expected_amount, f.variance, f.explanation, f.evidence_event_ids.join(" "),
  ]);
  const csv = [header, ...rows].map((r) => r.map(cell).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `revenue-leakage-${patientId || "patient"}-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
