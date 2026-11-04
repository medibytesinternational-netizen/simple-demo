// Brings fixture responses captured from the earlier backend up to the current API contract.
// Every added field is derived from the fixtures themselves with the backend's own rules
// (named beside each step), so the preview never shows a fact the synthetic record lacks.
// Fields the frontend does not read, or that cannot be derived honestly, are left out.

type Json = Record<string, any>;

const TIMELINE_KEY = "/patients/pat_ravi/timeline?limit=250";
const CLOSED_TASK_STATES = new Set(["completed", "cancelled"]);

// backend/app/services/identity.py: the one demo user and the actions the doctor role may take.
// The preview still refuses every write; these only decide which buttons are shown.
const PREVIEW_USER = { id: "u_meera", name: "Dr. Meera Shah", role: "doctor", home: "/timeline" };
const DOCTOR_ACTIONS = [
  "accept_tasks", "acknowledge_alert", "approve_draft", "buy_credits", "clinical_draft", "confirm_document",
  "consent", "discharge_draft", "dismiss_alert", "edit_draft", "give_medicine", "manage_task", "order_medicine",
  "reconcile", "record_reading", "records_request", "reject_draft", "resolve_discrepancy", "revenue_work",
  "review_lab", "run_rules", "send_request", "upload_document", "verify_allergy", "work_task",
];

// backend/app/routes/meta.py SOURCE_LABELS and source_label().
const SOURCE_LABELS: Record<string, string> = {
  F1: "Consultation note draft",
  F2: "Admission note draft",
  F3: "Round note draft",
  F4: "Progress note draft",
  F6: "Medicine reconciliation draft",
  F7: "ICU flow sheet draft",
  F9: "Discharge summary draft",
  F10: "Investigation request draft",
  F11: "Referral draft",
  F12: "Claim review draft",
  F13: "Revenue review draft",
  consent: "Consent record",
  lab: "Lab report scan",
  device: "Bedside device reading",
  seed: "MediBytes patient records",
  human: "Typed by a person",
};

function sourceLabel(source?: string | null) {
  const raw = (source || "").trim();
  if (!raw) return "Unknown source";
  if (raw.toLowerCase().startsWith("fhir:")) return raw;
  if (SOURCE_LABELS[raw]) return SOURCE_LABELS[raw];
  const text = raw.replaceAll("_", " ").trim();
  return text.slice(0, 1).toUpperCase() + text.slice(1);
}

// backend/app/routes/meta.py enrich_event(): who drafted, recorded and approved each event.
function enrichEvent(event: Json, events: Json[]): Json {
  if (event.authorship !== undefined) return event;
  const isModel = event.author_type === "model";
  const author = event.author_name || "Unknown";
  const approver = event.approved_by ?? null;
  const replacer = events.filter((other) => other.supersedes_event_id === event.id).pop();
  return {
    ...event,
    drafted_by: isModel ? author : null,
    recorded_by: isModel ? approver || author : author,
    authorship: isModel
      ? approver ? `Drafted by ${author}, approved by ${approver}` : `Drafted by ${author}, not yet approved`
      : `Recorded by ${author}`,
    approved_by: approver,
    ai_drafted: isModel,
    source_label: sourceLabel(event.source),
    superseded_by: replacer ? replacer.id : null,
  };
}

// The backend reads a bare date as midnight; compare everything as local wall-clock time.
const when = (value: string) => new Date(value.length === 10 ? `${value}T00:00:00` : value).getTime();

/** GET /patients/{id}/timeline with the F16 filters. Only the chart patient has a timeline in the fixtures. */
export function timeline(data: Json, patientId: string, query: string): Json | undefined {
  const base = data[TIMELINE_KEY];
  if (!base || patientId !== "pat_ravi") return undefined;
  const all: Json[] = base.events || [];
  const params = new URLSearchParams(query);
  const types = (params.get("types") || "").split(",").map((t) => t.trim()).filter(Boolean);
  const source = params.get("source");
  const before = params.get("before");
  const after = params.get("after");
  const limit = Number(params.get("limit") || 200);
  const events = all
    .filter((e) => !types.length || types.includes(e.type))
    .filter((e) => !source || String(e.source || "").toLowerCase() === source.trim().toLowerCase())
    .filter((e) => !before || when(e.occurred_at) < when(before))
    .filter((e) => !after || when(e.occurred_at) >= when(after))
    .sort((a, b) => when(b.occurred_at) - when(a.occurred_at))
    .slice(0, limit)
    .map((e) => enrichEvent(e, all));
  const sources = Array.from(new Set(all.map((e) => e.source).filter(Boolean))).sort() as string[];
  return {
    events,
    count: events.length,
    facets: {
      types: Array.from(new Set(all.map((e) => e.type).filter(Boolean))).sort(),
      sources: sources.map((s) => ({ source: s, label: sourceLabel(s) })),
    },
    filters: { types, source, before, after },
  };
}

/** GET /events/{id}: the same provenance, plus the versions it replaced (none in the fixtures). */
export function eventDetail(data: Json, event: Json): Json {
  const all: Json[] = data[TIMELINE_KEY]?.events || [];
  return { ...enrichEvent(event, all), supersedes: [] };
}

// backend/app/services/reconciliation.py _merge_decision(): the snapshot holds no decisions,
// so every difference is still open. The drug is the home-list label without its dose.
function reconciliation(value: Json): Json {
  const discrepancies = (value.discrepancies || []).map((item: Json) => ({
    status: "open",
    decision: null,
    note: null,
    decided_by: null,
    decided_at: null,
    earlier_decision: null,
    drug: item.drug ?? String(item.home_med || "").split(/\s+(?=\d)/)[0],
    ...item,
  }));
  return {
    ...value,
    discrepancies,
    unresolved_count: value.unresolved_count ?? discrepancies.filter((d: Json) => d.status === "open").length,
  };
}

// backend/app/services/approval/f09_discharge.py discharge_readiness(): warnings that need a
// written reason at sign-off, taken from the alert, task and reconciliation fixtures.
function readiness(value: Json, data: Json): Json {
  if (value.warnings) return value;
  const alerts: Json[] = data["/alerts"]?.alerts || [];
  const tasks: Json[] = data["/tasks"]?.tasks || [];
  const differences = reconciliation(data["/medications/reconciliation"] || {}).discrepancies as Json[];
  const warnings = {
    open_critical_alerts: alerts
      .filter((a) => a.status === "open" && a.severity === "critical")
      .map((a) => ({ id: a.id, title: a.title })),
    open_tasks: tasks.filter((t) => !CLOSED_TASK_STATES.has(t.status)).map((t) => ({ id: t.id, title: t.title })),
    unresolved_medicine_differences: differences
      .filter((d) => d.status === "open")
      .map((d) => ({ id: d.id, title: `${d.drug} - ${String(d.kind).replaceAll("_", " ")}` })),
  };
  return { ...value, warnings, needs_override: Object.values(warnings).some((list) => list.length > 0) };
}

/** Fills in what the current frontend reads for a response looked up by its path without the query. */
export function upgrade(bare: string, value: Json, data: Json): Json {
  if (!value || typeof value !== "object") return value;
  switch (bare) {
    case "/meta":
      return { ...value, user: value.user ?? PREVIEW_USER, allowed_actions: value.allowed_actions ?? DOCTOR_ACTIONS };
    case "/medications/reconciliation":
      return reconciliation(value);
    case "/discharge/readiness":
      return readiness(value, data);
    default:
      return value;
  }
}
