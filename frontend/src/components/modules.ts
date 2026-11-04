// Single navigation registry for the whole shell: the dock, the launchpad and
// the header breadcrumbs all read from here, so they always agree. Routes and
// ?tab= values are the existing ones.

export type CountKey = "alerts" | "overdue" | "documents" | "labs";

export type NavItem = {
  id: string;
  label: string;
  to: string;
  icon: string;
  /** Short plain-language purpose, shown under the label in the launchpad. */
  hint: string;
  match: (path: string, tab: string | null) => boolean;
  count?: CountKey;
  /** Extra words the launchpad search should match. */
  keywords?: string[];
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
      { id: "patients", label: "Patient list", to: "/patients", icon: "patients", hint: "Find, register and view patients", match: (p) => p === "/patients", keywords: ["register", "directory", "mrn"] },
      { id: "overview-patient", label: "Patient dashboard", to: "/patient", icon: "overview", hint: "Summary of the open patient: alerts, labs, medicines and next steps", match: (p) => p === "/patient", keywords: ["summary", "overview", "ravi"] },
      { id: "timeline", label: "Patient chart", to: "/timeline", icon: "chart", hint: "Timeline of everything recorded for the patient", match: (p) => p === "/timeline", keywords: ["timeline", "history", "events", "ravi"] },
    ],
  },
  {
    id: "clinical",
    title: "Clinical care",
    items: [
      { id: "consult", label: "OPD consultation", to: "/notes?tab=consult", icon: "consult", hint: "Record a consultation and review the draft note", match: tabIs("/notes", "consult", true), keywords: ["opd", "voice", "transcript", "outpatient"] },
      { id: "new-admission", label: "New admission", to: "/admission", icon: "admission", hint: "Admit a patient to a ward and bed", match: (p) => p === "/admission", keywords: ["bed", "ward", "admit"] },
      { id: "admission", label: "Admission assessment", to: "/notes?tab=admission", icon: "progress", hint: "Review the admission note and verify allergies", match: tabIs("/notes", "admission") },
      { id: "round", label: "Ward round", to: "/notes?tab=round", icon: "round", hint: "Round note, nursing entries and proposed tasks", match: tabIs("/notes", "round"), keywords: ["nursing", "handover"] },
      { id: "progress", label: "Progress notes", to: "/notes?tab=progress", icon: "progress", hint: "Daily note; examination and plan written by the clinician", match: tabIs("/notes", "progress") },
      { id: "icu", label: "ICU flow sheet", to: "/notes?tab=icu", icon: "icu", hint: "Device readings assembled into a chart", match: tabIs("/notes", "icu"), keywords: ["vitals", "device", "monitor"] },
      { id: "referral", label: "Referrals", to: "/notes?tab=referral", icon: "referral", hint: "Specialist referral and its status", match: tabIs("/notes", "referral") },
      { id: "discharge", label: "Discharge", to: "/discharge", icon: "discharge", hint: "Discharge summary, medicines and sign-off", match: (p) => p === "/discharge", keywords: ["summary", "sign off"] },
    ],
  },
  {
    id: "safety",
    title: "Safety & results",
    items: [
      { id: "alerts", label: "Clinical alerts", to: "/safety?tab=alerts", icon: "safety", hint: "Safety alerts to acknowledge or dismiss with a reason", match: tabIs("/safety", "alerts", true), count: "alerts" },
      { id: "meds", label: "Medication reconciliation", to: "/safety?tab=meds", icon: "pill", hint: "Home medicines compared with current orders", match: tabIs("/safety", "meds"), keywords: ["medicine", "drugs", "orders"] },
      { id: "labs", label: "Lab results", to: "/notes?tab=labs", icon: "lab", hint: "Results and abnormal values to review", match: tabIs("/notes", "labs"), count: "labs", keywords: ["results", "blood", "upload"] },
    ],
  },
  {
    id: "documents",
    title: "Documents & investigations",
    items: [
      { id: "inbound", label: "Inbound reports", to: "/documents?tab=inbound", icon: "scan", hint: "Outside reports read by OCR, confirmed by a person", match: tabIs("/documents", "inbound", true), count: "documents", keywords: ["ocr", "scan", "upload"] },
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
      { id: "claim", label: "Claim review", to: "/revenue?tab=claim", icon: "billing", hint: "Claim checklist and contradictions (review only)", match: tabIs("/revenue", "claim", true), keywords: ["insurance", "tpa", "bill"] },
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

export type DockItem = { id: string; label: string; to: string; icon: string; match: (p: string, t: string | null) => boolean; count?: CountKey; optional?: boolean };

/** Pages that act on the open patient: the patient bar and the patient dock show on exactly these. */
export const PATIENT_ROUTES = new Set(["/patient", "/timeline", "/notes", "/safety", "/documents", "/discharge", "/revenue", "/tasks"]);
export const isPatientRoute = (path: string) => PATIENT_ROUTES.has(path);

/** Dock outside a patient: hospital-wide pages. Every module is in the launchpad. */
export const HOSPITAL_DOCK: DockItem[] = [
  { id: "dashboard", label: "Dashboard", to: "/dashboard", icon: "overview", match: (p) => p === "/dashboard" },
  { id: "patients", label: "Patients", to: "/patients", icon: "patients", match: (p) => p === "/patients" },
  { id: "audit", label: "Audit", to: "/audit", icon: "audit", match: (p) => p === "/audit", optional: true },
];

/** Dock inside a patient's record: that patient's tabs. */
export const PATIENT_DOCK: DockItem[] = [
  { id: "overview", label: "Overview", to: "/patient", icon: "overview", match: (p) => p === "/patient" },
  { id: "chart", label: "Chart", to: "/timeline", icon: "chart", match: (p) => p === "/timeline" },
  { id: "care", label: "Care", to: "/notes?tab=round", icon: "round", match: (p, t) => p === "/notes" && t !== "labs" },
  // Labs live under Safety even though the URL starts with /notes.
  { id: "safety", label: "Safety", to: "/safety?tab=alerts", icon: "safety", match: (p, t) => p === "/safety" || (p === "/notes" && t === "labs"), count: "alerts" },
  { id: "documents", label: "Documents", to: "/documents?tab=inbound", icon: "scan", match: (p) => p === "/documents", count: "documents", optional: true },
  { id: "tasks", label: "Tasks", to: "/tasks", icon: "tasks", match: (p) => p === "/tasks", count: "overdue", optional: true },
  { id: "discharge", label: "Discharge", to: "/discharge", icon: "discharge", match: (p) => p === "/discharge", optional: true },
  { id: "billing", label: "Billing", to: "/revenue?tab=claim", icon: "billing", match: (p) => p === "/revenue", optional: true },
];

/** Badge colour per count: red for safety, amber for overdue work, blue for review queues. */
export const COUNT_TONE: Record<CountKey, "critical" | "warning" | "info"> = { alerts: "critical", overdue: "warning", documents: "info", labs: "info" };
