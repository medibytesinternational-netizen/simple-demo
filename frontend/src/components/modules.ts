// Single navigation registry for the whole shell: the sidebar, the bottom dock
// and the header breadcrumbs all read from here, so they
// always agree. Routes and ?tab= values are the existing ones.

export type NavItem = {
  id: string;
  label: string;
  to: string;
  icon: string;
  /** Short plain-language purpose, shown as the sidebar tooltip. */
  hint: string;
  match: (path: string, tab: string | null) => boolean;
  count?: "alerts" | "overdue";
};

export type NavGroup = { id: string; title: string; items: NavItem[] };

// Pages with tabs open on their first tab when no ?tab= is given.
const tabIs = (path: string, wanted: string, fallback?: boolean) =>
  (p: string, t: string | null) => p === path && (t === wanted || (fallback === true && !t));

export const NAV_GROUPS: NavGroup[] = [
  {
    id: "overview",
    title: "Overview",
    items: [
      { id: "dashboard", label: "Dashboard", to: "/dashboard", icon: "overview", hint: "What needs attention across the hospital", match: (p) => p === "/dashboard" },
    ],
  },
  {
    id: "patients",
    title: "Patients",
    items: [
      { id: "patients", label: "Patient list", to: "/patients", icon: "patients", hint: "Find, register and view patients", match: (p) => p === "/patients" },
      { id: "timeline", label: "Patient chart", to: "/timeline", icon: "chart", hint: "Timeline of everything recorded for the patient", match: (p) => p === "/timeline" },
    ],
  },
  {
    id: "clinical",
    title: "Clinical care",
    items: [
      { id: "consult", label: "OPD consultation", to: "/notes?tab=consult", icon: "consult", hint: "Record a consultation and review the draft note", match: tabIs("/notes", "consult", true) },
      { id: "new-admission", label: "New admission", to: "/admission", icon: "admission", hint: "Admit a patient to a ward and bed", match: (p) => p === "/admission" },
      { id: "admission", label: "Admission assessment", to: "/notes?tab=admission", icon: "progress", hint: "Review the admission note and verify allergies", match: tabIs("/notes", "admission") },
      { id: "round", label: "Ward round", to: "/notes?tab=round", icon: "round", hint: "Round note, nursing entries and proposed tasks", match: tabIs("/notes", "round") },
      { id: "progress", label: "Progress notes", to: "/notes?tab=progress", icon: "progress", hint: "Daily note; examination and plan written by the clinician", match: tabIs("/notes", "progress") },
      { id: "icu", label: "ICU flow sheet", to: "/notes?tab=icu", icon: "icu", hint: "Device readings assembled into a chart", match: tabIs("/notes", "icu") },
      { id: "referral", label: "Referrals", to: "/notes?tab=referral", icon: "referral", hint: "Specialist referral and its status", match: tabIs("/notes", "referral") },
      { id: "discharge", label: "Discharge", to: "/discharge", icon: "discharge", hint: "Discharge summary, medicines and sign-off", match: (p) => p === "/discharge" },
    ],
  },
  {
    id: "safety",
    title: "Safety & results",
    items: [
      { id: "alerts", label: "Clinical alerts", to: "/safety?tab=alerts", icon: "safety", hint: "Safety alerts to acknowledge or dismiss with a reason", match: tabIs("/safety", "alerts", true), count: "alerts" },
      { id: "meds", label: "Medication reconciliation", to: "/safety?tab=meds", icon: "pill", hint: "Home medicines compared with current orders", match: tabIs("/safety", "meds") },
      { id: "labs", label: "Lab results", to: "/notes?tab=labs", icon: "lab", hint: "Results and abnormal values to review", match: tabIs("/notes", "labs") },
    ],
  },
  {
    id: "documents",
    title: "Documents & investigations",
    items: [
      { id: "inbound", label: "Inbound reports", to: "/documents?tab=inbound", icon: "scan", hint: "Outside reports read by OCR, confirmed by a person", match: tabIs("/documents", "inbound", true) },
      { id: "requisition", label: "Investigation requests", to: "/documents?tab=requisition", icon: "request", hint: "Imaging and lab requests", match: tabIs("/documents", "requisition") },
      { id: "followup", label: "Records follow-up", to: "/documents?tab=followup", icon: "folder", hint: "Missing records and pre-authorisation requests", match: tabIs("/documents", "followup") },
    ],
  },
  {
    id: "work",
    title: "Work management",
    items: [
      { id: "tasks", label: "Tasks & escalations", to: "/tasks", icon: "tasks", hint: "Care tasks, owners, due times and escalation", match: (p) => p === "/tasks", count: "overdue" },
    ],
  },
  {
    id: "billing",
    title: "Billing",
    items: [
      { id: "claim", label: "Claim review", to: "/revenue?tab=claim", icon: "billing", hint: "Claim checklist and contradictions (review only)", match: tabIs("/revenue", "claim", true) },
      { id: "leakage", label: "Revenue leakage", to: "/revenue?tab=leakage", icon: "leakage", hint: "Documented care compared with the bill", match: tabIs("/revenue", "leakage") },
    ],
  },
  {
    id: "admin",
    title: "Administration",
    items: [
      { id: "audit", label: "Audit log", to: "/audit", icon: "audit", hint: "Every write, approval and model call", match: (p) => p === "/audit" },
    ],
  },
];

export const ALL_ITEMS = NAV_GROUPS.flatMap((g) => g.items.map((item) => ({ ...item, group: g.title })));

export function findActive(path: string, tab: string | null) {
  return ALL_ITEMS.find((item) => item.match(path, tab)) || null;
}

/** A few high-traffic shortcuts for the bottom dock. Every module is in the sidebar. */
export const DOCK_ITEMS: { id: string; label: string; to: string; icon: string; match: (p: string, t: string | null) => boolean; count?: "alerts" | "overdue" }[] = [
  { id: "dashboard", label: "Dashboard", to: "/dashboard", icon: "overview", match: (p) => p === "/dashboard" },
  { id: "patients", label: "Patients", to: "/patients", icon: "patients", match: (p) => p === "/patients" || p === "/timeline" },
  { id: "clinical", label: "Clinical care", to: "/notes?tab=round", icon: "round", match: (p, t) => (p === "/notes" && t !== "labs") || p === "/admission" || p === "/discharge" },
  { id: "alerts", label: "Alerts", to: "/safety?tab=alerts", icon: "safety", match: (p) => p === "/safety", count: "alerts" },
  { id: "tasks", label: "Tasks", to: "/tasks", icon: "tasks", match: (p) => p === "/tasks", count: "overdue" },
];
