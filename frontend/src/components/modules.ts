// Single navigation registry for the whole shell: the sidebar, the Ctrl+K search
// and the page title all read from here, so they always agree. Routes and
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

/** hospital = hospital-wide pages; patient = pages about the open patient. */
export type NavGroup = { id: string; title: string; scope: "hospital" | "patient"; items: NavItem[] };

// Pages with tabs open on their first tab when no ?tab= is given.
const tabIs = (path: string, wanted: string, fallback?: boolean) =>
  (p: string, t: string | null) => p === path && (t === wanted || (fallback === true && !t));

export const NAV_GROUPS: NavGroup[] = [
  {
    id: "hospital",
    title: "Hospital",
    scope: "hospital",
    items: [
      { id: "dashboard", label: "Dashboard", to: "/dashboard", icon: "overview", hint: "What needs attention across the hospital", match: (p) => p === "/dashboard" },
      { id: "new-patient", label: "New patient", to: "/patients/new", icon: "plus", hint: "Register, record the consultation and add previous reports", match: (p) => p === "/patients/new", keywords: ["register", "add", "opd", "admit", "upload"] },
      { id: "patients", label: "Patient list", to: "/patients", icon: "patients", hint: "Find, register and view patients", match: (p) => p === "/patients", keywords: ["register", "directory", "mrn"] },
      { id: "audit", label: "Audit logs", to: "/audit", icon: "audit", hint: "Monitoring log of every write, approval and model call", match: (p) => p === "/audit", keywords: ["monitoring"] },
    ],
  },
  {
    id: "patient",
    title: "Patient record",
    scope: "patient",
    items: [
      { id: "overview-patient", label: "Overview", to: "/patient", icon: "overview", hint: "Summary of the open patient: alerts, labs, medicines and next steps", match: (p) => p === "/patient", keywords: ["summary", "overview", "ravi"] },
      { id: "timeline", label: "Chart", to: "/timeline", icon: "chart", hint: "Timeline of everything recorded for the patient", match: (p) => p === "/timeline", keywords: ["timeline", "history", "events", "ravi"] },
      { id: "patient-progress", label: "Progress", to: "/progress", icon: "chart", hint: "Overall progress from OPD to discharge, and daily task and note progress", match: (p) => p === "/progress", keywords: ["daily", "overall", "verified", "complete"] },
    ],
  },
  {
    id: "clinical",
    title: "Clinical care",
    scope: "patient",
    items: [
      { id: "consult", label: "OPD consultation", to: "/notes?tab=consult", icon: "consult", hint: "Record a consultation and review the draft note", match: tabIs("/notes", "consult", true), keywords: ["opd", "voice", "transcript", "outpatient"] },
      { id: "admission", label: "Admission assessment", to: "/notes?tab=admission", icon: "admission", hint: "Admission note from the interview; verify allergies first", match: tabIs("/notes", "admission"), keywords: ["admit", "allergy"] },
      { id: "round", label: "Ward round", to: "/notes?tab=round", icon: "round", hint: "Round note, nursing entries and proposed tasks", match: tabIs("/notes", "round"), keywords: ["nursing", "handover"] },
      { id: "progress", label: "Progress notes", to: "/notes?tab=progress", icon: "progress", hint: "Daily note; examination and plan written by the clinician", match: tabIs("/notes", "progress") },
      { id: "icu", label: "ICU flow sheet", to: "/notes?tab=icu", icon: "icu", hint: "Device readings assembled into a chart", match: tabIs("/notes", "icu"), keywords: ["vitals", "device", "monitor"] },
      { id: "referral", label: "Referrals", to: "/notes?tab=referral", icon: "referral", hint: "Specialist referral and its status", match: tabIs("/notes", "referral") },
      { id: "discharge", label: "Discharge", to: "/discharge", icon: "discharge", hint: "Discharge summary, medicines and sign-off", match: (p) => p === "/discharge", keywords: ["summary", "sign off"] },
    ],
  },
  {
    id: "safety",
    title: "Alerts & labs",
    scope: "patient",
    items: [
      { id: "alerts", label: "Clinical alerts", to: "/safety?tab=alerts", icon: "safety", hint: "Safety alerts to acknowledge or dismiss with a reason", match: tabIs("/safety", "alerts", true), count: "alerts" },
      { id: "meds", label: "Medicine check", to: "/safety?tab=meds", icon: "pill", hint: "Home medicines compared with current orders", match: tabIs("/safety", "meds"), keywords: ["medicine", "drugs", "orders"] },
      { id: "labs", label: "Lab results", to: "/notes?tab=labs", icon: "lab", hint: "Results and abnormal values to review", match: tabIs("/notes", "labs"), count: "labs", keywords: ["results", "blood", "upload"] },
    ],
  },
  {
    id: "documents",
    title: "Reports & requests",
    scope: "patient",
    items: [
      { id: "inbound", label: "Inbound reports", to: "/documents?tab=inbound", icon: "scan", hint: "Outside reports read by OCR, confirmed by a person", match: tabIs("/documents", "inbound", true), count: "documents", keywords: ["ocr", "scan", "upload"] },
      { id: "requisition", label: "Investigation requests", to: "/documents?tab=requisition", icon: "request", hint: "Imaging and lab requests", match: tabIs("/documents", "requisition") },
      { id: "followup", label: "Records follow-up", to: "/documents?tab=followup", icon: "folder", hint: "Missing records and pre-authorisation requests", match: tabIs("/documents", "followup") },
    ],
  },
  {
    id: "work",
    title: "Work",
    scope: "patient",
    items: [
      { id: "tasks", label: "Tasks", to: "/tasks", icon: "tasks", hint: "Care tasks, owners, due times and escalation", match: (p) => p === "/tasks", count: "overdue" },
    ],
  },
  {
    id: "billing",
    title: "Billing",
    scope: "patient",
    items: [
      { id: "claim", label: "Claim review", to: "/revenue?tab=claim", icon: "billing", hint: "Claim checklist and contradictions (review only)", match: tabIs("/revenue", "claim", true), keywords: ["insurance", "tpa", "bill"] },
      { id: "leakage", label: "Revenue leakage", to: "/revenue?tab=leakage", icon: "leakage", hint: "Documented care compared with the bill", match: tabIs("/revenue", "leakage") },
    ],
  },
];

export const ALL_ITEMS = NAV_GROUPS.flatMap((g) => g.items.map((item) => ({ ...item, group: g.title })));

export function findActive(path: string, tab: string | null) {
  return ALL_ITEMS.find((item) => item.match(path, tab)) || null;
}

/** Pages that act on the open patient: the patient bar and the patient dock show on exactly these. */
export const PATIENT_ROUTES = new Set(["/patient", "/timeline", "/progress", "/notes", "/safety", "/documents", "/discharge", "/revenue", "/tasks"]);
export const isPatientRoute = (path: string) => PATIENT_ROUTES.has(path);

/** Badge colour per count: red for safety, amber for overdue work, blue for review queues. */
export const COUNT_TONE: Record<CountKey, "critical" | "warning" | "info"> = { alerts: "critical", overdue: "warning", documents: "info", labs: "info" };
