// Navigation registry. The left navigation follows the demo flow from
// "MediBytes ARD — Demo Architecture and UI Flow": one patient, eight screens, one path.
// Routes and ?tab= values are the existing ones.

export type ModuleLink = {
  id: string;
  label: string;
  to: string;
  icon: string;
  code?: string;
  action?: "audit";
};

export type FlowStep = ModuleLink & {
  step: number;
  hint: string;
  match: (path: string, tab: string | null) => boolean;
  count?: "alerts";
};

/** The eight screens in demo order. Each ends in an approval that feeds the next screen. */
export const FLOW_STEPS: FlowStep[] = [
  { step: 1, id: "timeline", label: "Timeline", hint: "Everything that happened", code: "F16", to: "/timeline", icon: "chart",
    match: (p) => p === "/timeline" },
  { step: 2, id: "consult", label: "Consultation", hint: "Record, review note, sign", code: "F1", to: "/notes?tab=consult", icon: "consult",
    match: (p, t) => p === "/notes" && (!t || t === "consult") },
  { step: 3, id: "alerts", label: "Alerts", hint: "Act or dismiss with reason", code: "F5 F6", to: "/safety?tab=alerts", icon: "safety",
    match: (p) => p === "/safety", count: "alerts" },
  { step: 4, id: "round", label: "Ward round", hint: "Note plus proposed tasks", code: "F3 F4 F15", to: "/notes?tab=round", icon: "round",
    match: (p, t) => (p === "/notes" && (t === "round" || t === "progress")) || p === "/tasks" },
  { step: 5, id: "documents", label: "Documents", hint: "Upload, confirm extraction", code: "F8 F10", to: "/documents?tab=inbound", icon: "scan",
    match: (p) => p === "/documents" },
  { step: 6, id: "discharge", label: "Discharge", hint: "Summary with evidence", code: "F9 F11", to: "/discharge", icon: "discharge",
    match: (p, t) => p === "/discharge" || (p === "/notes" && t === "referral") },
  { step: 7, id: "claims", label: "Claims", hint: "Checklist, leakage queue", code: "F12 F13", to: "/revenue?tab=claim", icon: "billing",
    match: (p) => p === "/revenue" },
  { step: 8, id: "dashboard", label: "Dashboard", hint: "Counters and turnaround", code: "F14", to: "/dashboard", icon: "overview",
    match: (p) => p === "/dashboard" },
];

/** Modules that are not a step of their own, but must stay one click away. */
export const MORE_LINKS: (ModuleLink & { match?: (path: string, tab: string | null) => boolean })[] = [
  { id: "patients", label: "Patients", to: "/patients", icon: "patients", match: (p) => p === "/patients" },
  { id: "new-admission", label: "New admission", to: "/admission", icon: "admission", match: (p) => p === "/admission" },
  { id: "admission", label: "Admission assessment", code: "F2", to: "/notes?tab=admission", icon: "progress", match: (p, t) => p === "/notes" && t === "admission" },
  { id: "icu", label: "ICU chart", code: "F7", to: "/notes?tab=icu", icon: "icu", match: (p, t) => p === "/notes" && t === "icu" },
  { id: "labs", label: "Lab results", to: "/notes?tab=labs", icon: "lab", match: (p, t) => p === "/notes" && t === "labs" },
  { id: "tasks", label: "Tasks", code: "F15", to: "/tasks", icon: "tasks", match: (p) => p === "/tasks" },
  { id: "audit", label: "Audit log", to: "", icon: "audit", action: "audit" },
];

/** Every module, grouped, for the searchable launcher. */
export const LAUNCHER_GROUPS: { title: string; items: ModuleLink[] }[] = [
  {
    title: "Demo path",
    items: FLOW_STEPS.map(({ id, label, to, icon, code, step }) => ({ id: `flow-${id}`, label: `${step}. ${label}`, to, icon, code })),
  },
  {
    title: "Patients & inpatient care",
    items: [
      { id: "plist", label: "Patient list", to: "/patients", icon: "patients" },
      { id: "new-admission", label: "New admission", to: "/admission", icon: "admission" },
      { id: "admission", label: "Admission assessment", to: "/notes?tab=admission", icon: "progress", code: "F2" },
      { id: "progress", label: "Progress note", to: "/notes?tab=progress", icon: "progress", code: "F4" },
      { id: "icu", label: "ICU flow sheet", to: "/notes?tab=icu", icon: "icu", code: "F7" },
      { id: "referral", label: "Referral", to: "/notes?tab=referral", icon: "referral", code: "F11" },
    ],
  },
  {
    title: "Safety, results & documents",
    items: [
      { id: "meds", label: "Medication reconciliation", to: "/safety?tab=meds", icon: "pill", code: "F6" },
      { id: "labs", label: "Lab results", to: "/notes?tab=labs", icon: "lab", code: "Labs" },
      { id: "requisition", label: "Investigation requests", to: "/documents?tab=requisition", icon: "request", code: "F10" },
      { id: "followup", label: "Records follow-up", to: "/documents?tab=followup", icon: "folder" },
    ],
  },
  {
    title: "Operations & billing",
    items: [
      { id: "tasks", label: "Tasks & escalations", to: "/tasks", icon: "tasks", code: "F15" },
      { id: "audit", label: "Audit log", to: "", icon: "audit", action: "audit" },
      { id: "leakage", label: "Revenue leakage", to: "/revenue?tab=leakage", icon: "leakage", code: "F13" },
    ],
  },
];
