import { useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "../api";
import type { Alert, AppTask, DocumentSummary, Draft, HospitalDashboard, InvestigationRequest, Meta } from "../types";
import { DEMO_MODE } from "../demo/config";
import { Icon } from "../components/icons";
import { WARDS } from "../components/wards";

type Row = HospitalDashboard["patients"][number];
type Tone = "critical" | "attention" | "info" | "neutral";

// Only the primary synthetic patient has a full clinical chart in the current backend.
const CHART_PATIENT_ID = "pat_ravi";
const PENDING_DRAFT = new Set(["draft_ready", "human_edited", "model_unavailable"]);

// Draft-producing modules and the existing screen where each draft is reviewed.
const DRAFT_SCREENS: { feature: string; label: string; to: string }[] = [
  { feature: "F1", label: "consultation note", to: "/notes?tab=consult" },
  { feature: "F2", label: "admission assessment", to: "/notes?tab=admission" },
  { feature: "F3", label: "ward round note", to: "/notes?tab=round" },
  { feature: "F4", label: "progress note", to: "/notes?tab=progress" },
  { feature: "F7", label: "ICU flow sheet", to: "/notes?tab=icu" },
  { feature: "F11", label: "referral letter", to: "/notes?tab=referral" },
  { feature: "F6", label: "medication reconciliation summary", to: "/safety?tab=meds" },
  { feature: "F9", label: "discharge summary", to: "/discharge" },
  { feature: "F10", label: "investigation request", to: "/documents?tab=requisition" },
  { feature: "F12", label: "claim review explanation", to: "/revenue?tab=claim" },
  { feature: "F13", label: "revenue leakage explanation", to: "/revenue?tab=leakage" },
];

type Referral = { id: string; specialty: string; status: string; urgency?: string };

type NextAction = {
  key: string;
  tone: Tone;
  icon: string;
  status: string;
  title: string;
  why: string;
  patient?: Row;
  action: string;
  to: string;
  rank: number;
};

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const place = (row?: Row) => (row ? [row.ward, row.bed].filter(Boolean).join(" · ") : "");
const initials = (name: string) => name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();

function greetingFor(demoNow?: string) {
  if (!demoNow) return "Welcome";
  const hour = new Date(demoNow).getHours();
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

function shortName(user?: string) {
  if (!user) return "";
  const parts = user.split(" ");
  return parts[0].toLowerCase().startsWith("dr") && parts[1] ? `${parts[0]} ${parts[1]}` : parts[0];
}

const VISIBLE_ACTIONS = 6;

export function DashboardPage() {
  const [ward, setWard] = useState("all");
  const [showAllActions, setShowAllActions] = useState(false);
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta") });
  const dashboard = useQuery<HospitalDashboard>({ queryKey: ["hospital-dashboard"], queryFn: () => get("/hospital/dashboard") });
  const alerts = useQuery<{ alerts: Alert[] }>({ queryKey: ["alerts"], queryFn: () => get("/alerts") });
  const tasks = useQuery<{ tasks: AppTask[] }>({ queryKey: ["tasks"], queryFn: () => get("/tasks") });
  const documents = useQuery<{ documents: DocumentSummary[] }>({ queryKey: ["documents"], queryFn: () => get("/documents") });
  const referrals = useQuery<{ referrals: Referral[] }>({ queryKey: ["referrals"], queryFn: () => get("/referrals") });
  const requests = useQuery<{ requests: InvestigationRequest[] }>({ queryKey: ["investigation-requests"], queryFn: () => get("/investigation-requests") });
  const drafts = useQueries({
    queries: DRAFT_SCREENS.map((d) => ({
      queryKey: ["drafts", d.feature],
      queryFn: () => get<{ drafts: Draft[] }>(`/drafts?feature=${d.feature}&limit=1`),
    })),
  });

  const data = dashboard.data;
  const summary = data?.summary;
  const rows = data?.patients || [];
  const byId = new Map(rows.map((r) => [r.patient_id, r]));
  const primary = byId.get(CHART_PATIENT_ID);

  // ---------- "What needs attention?" tiles (counts straight from /hospital/dashboard) ----------
  const firstDraft = DRAFT_SCREENS.find((d, i) => drafts[i].data?.drafts?.some((x) => PENDING_DRAFT.has(x.status)));
  const tiles = summary
    ? [
        {
          key: "alerts", icon: "safety", tone: (summary.critical_alerts ? "critical" : "neutral") as Tone,
          value: summary.critical_alerts, title: "Critical alerts",
          text: summary.critical_alerts
            ? `Safety checks found serious problems with medicines or records. ${plural(summary.open_alerts, "alert")} open in total.`
            : summary.open_alerts ? `No critical alerts. ${plural(summary.open_alerts, "lower-priority alert")} still open.` : "No safety alerts are open.",
          action: "Review alerts", to: "/safety?tab=alerts",
        },
        {
          key: "tasks", icon: "clock", tone: (summary.overdue_tasks ? "attention" : "neutral") as Tone,
          value: summary.overdue_tasks, title: "Overdue tasks",
          text: summary.overdue_tasks
            ? `Care tasks past their due time${summary.escalated_tasks ? `; ${summary.escalated_tasks} already escalated to a senior` : ""}.`
            : "Every care task is on time.",
          action: "View tasks", to: "/tasks",
        },
        {
          key: "drafts", icon: "chart", tone: (summary.pending_drafts ? "info" : "neutral") as Tone,
          value: summary.pending_drafts, title: "Notes & drafts to review",
          text: summary.pending_drafts
            ? "Written by AI. They are not part of the patient record until a clinician reviews and approves them."
            : "No drafts are waiting for review.",
          action: "Review notes", to: firstDraft?.to || "/notes",
        },
        {
          key: "patients", icon: "user", tone: "neutral" as Tone,
          value: summary.active_encounters, title: "Patients in care",
          text: `Active admissions and day-care visits, out of ${plural(summary.patients, "patient")} on record.`,
          action: "See patients", to: "/patients",
        },
      ]
    : [];

  // ---------- "Your next actions" (built only from records that exist) ----------
  const actions: NextAction[] = [];
  if (primary) {
    const open = (alerts.data?.alerts || []).filter((a) => a.status === "open");
    const critical = open.filter((a) => a.severity === "critical");
    const warnings = open.filter((a) => a.severity !== "critical");
    if (critical.length) {
      actions.push({
        key: "crit", tone: "critical", icon: "alert", status: "Critical", rank: 0,
        title: critical.length === 1 ? "Review a critical patient alert" : `Review ${critical.length} critical patient alerts`,
        why: critical.length === 1 ? critical[0].title : `For example: ${critical[0].title}`,
        patient: primary, action: "Review alerts", to: "/safety?tab=alerts",
      });
    }
    if (warnings.length) {
      actions.push({
        key: "warn", tone: "attention", icon: "alert", status: "Check", rank: 3,
        title: warnings.length === 1 ? "Check a patient alert" : `Check ${warnings.length} patient alerts`,
        why: warnings[0].title, patient: primary, action: "Review alerts", to: "/safety?tab=alerts",
      });
    }
    (tasks.data?.tasks || [])
      .filter((t) => t.is_overdue && !["completed", "cancelled"].includes(t.status))
      .forEach((t) => actions.push({
        key: `task-${t.id}`, tone: "attention", icon: "clock", status: t.escalation_level ? "Overdue · escalated" : "Overdue", rank: 1,
        title: `Complete: ${t.title}`, why: t.owner ? `Past its due time · assigned to ${t.owner}` : "Past its due time",
        patient: primary, action: "Open task", to: "/tasks",
      }));
    (documents.data?.documents || [])
      .filter((d) => d.ocr_status === "needs_confirmation" || d.ocr_status === "pending")
      .forEach((d) => actions.push({
        key: `doc-${d.id}`, tone: "attention", icon: "scan", status: "Verify", rank: 2,
        title: "Verify an incoming report",
        why: "Values read from an outside report must be checked by a person before they enter the record",
        patient: primary, action: "Verify report", to: "/documents?tab=inbound",
      }));
    (referrals.data?.referrals || [])
      .filter((r) => r.status === "sent")
      .forEach((r) => actions.push({
        key: `ref-${r.id}`, tone: "neutral", icon: "referral", status: "Waiting", rank: 5,
        title: `Follow up the ${r.specialty} referral`, why: "Sent, but the specialist has not acknowledged it yet",
        patient: primary, action: "Open referral", to: "/notes?tab=referral",
      }));
    (requests.data?.requests || [])
      .filter((r) => r.status === "approved")
      .forEach((r) => actions.push({
        key: `inv-${r.id}`, tone: "neutral", icon: "request", status: "Ready", rank: 6,
        title: `Send the request: ${r.study}`, why: "Approved and ready to send to the department",
        patient: primary, action: "Open request", to: "/documents?tab=requisition",
      }));
  }
  // AI drafts are grouped into one action so they do not crowd out urgent work.
  const pendingDrafts = DRAFT_SCREENS.map((screen, i) => ({ screen, draft: drafts[i].data?.drafts?.find((x) => PENDING_DRAFT.has(x.status)) }))
    .filter((d) => d.draft) as { screen: (typeof DRAFT_SCREENS)[number]; draft: Draft }[];
  if (pendingDrafts.length) {
    const names = pendingDrafts.map((d) => d.screen.label);
    const owners = Array.from(new Set(pendingDrafts.map((d) => d.draft.patient_id)));
    const unavailable = pendingDrafts.some((d) => d.draft.status === "model_unavailable");
    actions.push({
      key: "drafts", tone: "info", icon: "progress", status: "AI draft", rank: 4,
      title: pendingDrafts.length === 1 ? `Review the ${names[0]}` : `Review ${pendingDrafts.length} AI-written drafts`,
      why: `${names.slice(0, 3).join(", ")}${names.length > 3 ? ` and ${names.length - 3} more` : ""} — not approved until a clinician reviews them${unavailable ? " (one could not be generated)" : ""}`,
      patient: owners.length === 1 ? byId.get(owners[0]) : undefined,
      action: "Start reviewing", to: pendingDrafts[0].screen.to,
    });
  }
  rows
    .filter((r) => r.patient_id !== CHART_PATIENT_ID && r.encounter_status !== "discharged" && (r.open_alerts || r.overdue_tasks))
    .forEach((r) => {
      const why = [
        r.critical_alerts ? plural(r.critical_alerts, "critical alert") : "",
        r.open_alerts - r.critical_alerts > 0 ? plural(r.open_alerts - r.critical_alerts, "alert") : "",
        r.overdue_tasks ? `${plural(r.overdue_tasks, "overdue task")}${r.escalated_tasks ? " (escalated)" : ""}` : "",
      ].filter(Boolean).join(" · ");
      actions.push({
        key: `cohort-${r.patient_id}`, tone: r.critical_alerts ? "critical" : "attention", icon: r.critical_alerts ? "alert" : "clock",
        status: r.critical_alerts ? "Critical" : "Overdue", rank: r.critical_alerts ? 0.5 : 1.5,
        title: `Check on ${r.name}`, why: `${why} — details are in the patient summary`,
        patient: r, action: "View summary", to: `/patients?patient=${encodeURIComponent(r.patient_id)}`,
      });
    });
  actions.sort((a, b) => a.rank - b.rank);
  const detailsLoading = [alerts, tasks, documents, referrals, requests, ...drafts].some((q) => q.isLoading);
  const detailsFailed = [alerts, tasks, documents, referrals, requests, ...drafts].some((q) => q.isError);

  // ---------- Patients and wards ----------
  const wardOptions = Array.from(new Set(rows.map((r) => r.ward).filter(Boolean))) as string[];
  const patientRows = [...rows]
    .filter((r) => ward === "all" || r.ward === ward)
    .sort((a, b) => (b.critical_alerts * 100 + b.open_alerts * 10 + b.overdue_tasks - (b.encounter_status === "discharged" ? 1000 : 0))
      - (a.critical_alerts * 100 + a.open_alerts * 10 + a.overdue_tasks - (a.encounter_status === "discharged" ? 1000 : 0)) || a.name.localeCompare(b.name));
  const occupied = summary?.wards || {};
  const configured = new Map(WARDS.map((w) => [w.name, w.beds.length]));
  const wardNames = Array.from(new Set([...WARDS.map((w) => w.name), ...Object.keys(occupied)]));

  const demoClock = meta.data?.demo_now
    ? new Date(meta.data.demo_now).toLocaleString("en-GB", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })
    : null;
  const name = shortName(meta.data?.demo_user);

  return (
    <div className="gd-page">
      {/* A · Friendly introduction */}
      <header className="gd-hello">
        <div>
          <h1 className="gd-greeting">{greetingFor(meta.data?.demo_now)}{name ? `, ${name}` : ""}</h1>
          <p className="gd-lead">Here is what needs your attention today.</p>
          <p className="gd-context">
            <span className="gd-demo">{DEMO_MODE ? "Synthetic demo — UI preview only" : "Synthetic demo data"}</span>
            {demoClock ? <span>Demo clock: {demoClock}</span> : null}
            <span>All patients shown are fictional.</span>
          </p>
        </div>
        <button className="btn gd-refresh" onClick={() => { dashboard.refetch(); alerts.refetch(); tasks.refetch(); documents.refetch(); referrals.refetch(); requests.refetch(); drafts.forEach((d) => d.refetch()); }} disabled={dashboard.isFetching}>
          <Icon name="refresh" size={15} /> {dashboard.isFetching ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      {dashboard.isError ? (
        <div className="gd-error" role="alert">
          <Icon name="alert" size={20} />
          <div><strong>The hospital overview could not be loaded.</strong> {(dashboard.error as Error).message}</div>
          <button className="btn btn-sm" onClick={() => dashboard.refetch()}>Try again</button>
        </div>
      ) : null}

      {/* B · What needs attention? */}
      <section aria-labelledby="gd-attention">
        <h2 id="gd-attention" className="gd-h2">What needs attention?</h2>
        <p className="gd-h2-sub">Start with the red tile, then work left to right.</p>
        <div className="gd-tiles">
          {tiles.length ? tiles.map((t) => (
            <Link key={t.key} to={t.to} className={`gd-tile tone-${t.tone}`} aria-label={`${t.value} ${t.title}. ${t.action}`}>
              <span className="gd-tile-top">
                <span className="gd-tile-icon"><Icon name={t.icon} size={28} /></span>
                <span className="gd-tile-value">{t.value}</span>
              </span>
              <span className="gd-tile-title">{t.title}</span>
              <span className="gd-tile-text">{t.text}</span>
              <span className="gd-tile-action">{t.action} <Icon name="chevron" size={16} /></span>
            </Link>
          )) : [0, 1, 2, 3].map((i) => (
            <div key={i} className="gd-tile gd-tile-loading" aria-hidden="true">
              <span className="gd-tile-icon" /><span className="gd-skel" /><span className="gd-skel short" />
            </div>
          ))}
        </div>
      </section>

      <div className="gd-main">
        <div className="gd-col">
          {/* C · Your next actions */}
          <section className="gd-panel" aria-labelledby="gd-next">
            <div className="gd-panel-head">
              <div>
                <h2 id="gd-next" className="gd-h2">Your next actions</h2>
                <p className="gd-h2-sub">Most urgent first. Each item opens the screen where the work is done.</p>
              </div>
            </div>
            {dashboard.isLoading || (data && detailsLoading && !actions.length) ? <div className="gd-muted-block">Loading your work list…</div> : null}
            {data && !detailsLoading && !actions.length ? (
              <div className="gd-empty">
                <span className="gd-empty-icon"><Icon name="check" size={22} /></span>
                <div><strong>You are all caught up.</strong> No alerts, overdue tasks, reports or drafts are waiting.</div>
              </div>
            ) : null}
            <ol className="gd-actions">
              {(showAllActions ? actions : actions.slice(0, VISIBLE_ACTIONS)).map((a, index) => (
                <li key={a.key}>
                  <Link to={a.to} className={`gd-action tone-${a.tone}`}>
                    <span className="gd-step" aria-hidden="true">{index + 1}</span>
                    <span className="gd-action-icon" aria-hidden="true"><Icon name={a.icon} size={20} /></span>
                    <span className="gd-action-body">
                      <span className="gd-action-title">{a.title}</span>
                      <span className="gd-action-why">
                        <span className="gd-action-status">{a.status}</span>
                        {a.why}
                      </span>
                    </span>
                    <span className="gd-action-patient">
                      {a.patient ? <><strong>{a.patient.name}</strong><span>{place(a.patient) || a.patient.mrn}</span></> : <span className="gd-muted">Hospital-wide</span>}
                    </span>
                    <span className="gd-action-go">{a.action} <Icon name="chevron" size={16} /></span>
                  </Link>
                </li>
              ))}
            </ol>
            {actions.length > VISIBLE_ACTIONS ? (
              <button className="gd-more" onClick={() => setShowAllActions((v) => !v)} aria-expanded={showAllActions}>
                {showAllActions ? "Show fewer" : `Show all ${actions.length} actions`}
              </button>
            ) : null}
            {data && detailsFailed ? <p className="gd-foot">Some details could not be loaded, so this list may be incomplete. The tiles above still show the full counts.</p> : null}
          </section>

          {/* D · Patients */}
          <section className="gd-panel" aria-labelledby="gd-patients">
            <div className="gd-panel-head">
              <div>
                <h2 id="gd-patients" className="gd-h2">Patients</h2>
                <p className="gd-h2-sub">Patients needing attention are listed first.</p>
              </div>
              <div className="gd-panel-tools">
                <select className="select select-compact" value={ward} onChange={(e) => setWard(e.target.value)} aria-label="Show patients in ward">
                  <option value="all">All wards</option>
                  {wardOptions.map((w) => <option key={w}>{w}</option>)}
                </select>
                <Link className="link-action" to="/patients">Patient list <Icon name="chevron" size={14} /></Link>
              </div>
            </div>
            {dashboard.isLoading ? <div className="gd-muted-block">Loading patients…</div> : null}
            {data && !patientRows.length ? <div className="gd-muted-block">No patients in {ward}.</div> : null}
            <ul className="gd-patients">
              {patientRows.map((r) => {
                const discharged = r.encounter_status === "discharged";
                const status = discharged ? { tone: "neutral", icon: "discharge", text: "Discharged" }
                  : r.critical_alerts ? { tone: "critical", icon: "alert", text: plural(r.critical_alerts, "critical alert") }
                  : r.overdue_tasks ? { tone: "attention", icon: "clock", text: plural(r.overdue_tasks, "overdue task") }
                  : r.open_alerts ? { tone: "attention", icon: "alert", text: plural(r.open_alerts, "alert") + " to check" }
                  : { tone: "ok", icon: "check", text: "Nothing outstanding" };
                const chart = r.patient_id === CHART_PATIENT_ID;
                return (
                  <li key={r.patient_id} className={`gd-patient ${discharged ? "is-muted" : ""}`}>
                    <span className="gd-avatar" aria-hidden="true">{initials(r.name)}</span>
                    <span className="gd-patient-id">
                      <strong>{r.name}</strong>
                      <span>{place(r) || "No bed"}{r.kind ? ` · ${r.kind}` : ""} · {r.age} {r.sex.slice(0, 1)} · {r.mrn}</span>
                    </span>
                    <span className={`gd-patient-status tone-${status.tone}`}><Icon name={status.icon} size={16} /> {status.text}</span>
                    <span className="gd-patient-go">
                      {chart ? (
                        <Link className="btn btn-primary btn-sm" to="/timeline">Open chart</Link>
                      ) : (
                        <>
                          <span className="gd-summary-tag">Summary only</span>
                          <Link className="btn btn-sm" to={`/patients?patient=${encodeURIComponent(r.patient_id)}`}>View summary</Link>
                        </>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
            {data ? <p className="gd-foot">A full clinical chart exists for {primary?.name || "the primary patient"} only. Other patients have summary records.</p> : null}
          </section>
        </div>

        <aside className="gd-col gd-side">
          {/* E · Wards */}
          <section className="gd-panel" aria-labelledby="gd-wards">
            <div className="gd-panel-head"><h2 id="gd-wards" className="gd-h2">Wards</h2></div>
            {data ? (
              <ul className="gd-wards">
                {wardNames.map((w) => {
                  const used = occupied[w] || 0;
                  const total = configured.get(w);
                  return (
                    <li key={w} className="gd-ward">
                      <span className="gd-ward-name">{w}</span>
                      <span className="gd-ward-count">{total ? `${used} of ${total} beds in use` : `${plural(used, "patient")}`}</span>
                      {total ? (
                        <span className="gd-meter" role="img" aria-label={`${used} of ${total} beds in use`}>
                          <span style={{ width: `${Math.min(100, (used / total) * 100)}%` }} />
                        </span>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            ) : <div className="gd-muted-block">Loading wards…</div>}
            <p className="gd-foot">Beds in use = active admissions. Bed totals come from the bed list used by the admission form in this demo.</p>
          </section>

          {/* F · Start a task (navigation for first-time users) */}
          <section className="gd-panel" aria-labelledby="gd-start">
            <div className="gd-panel-head"><h2 id="gd-start" className="gd-h2">Start a task</h2></div>
            <ul className="gd-start">
              {[
                { icon: "patients", label: "Find or register a patient", to: "/patients" },
                { icon: "admission", label: "Admit a patient", to: "/admission" },
                { icon: "consult", label: "Outpatient consultation", to: "/notes?tab=consult" },
                { icon: "round", label: "Ward round notes", to: "/notes?tab=round" },
                { icon: "lab", label: "Lab results", to: "/notes?tab=labs" },
                { icon: "discharge", label: "Discharge a patient", to: "/discharge" },
                { icon: "billing", label: "Billing review", to: "/revenue" },
              ].map((s) => (
                <li key={s.to}>
                  <Link to={s.to} className="gd-start-link">
                    <span className="gd-start-icon" aria-hidden="true"><Icon name={s.icon} size={18} /></span>
                    {s.label}
                    <Icon name="chevron" size={16} className="gd-start-chev" />
                  </Link>
                </li>
              ))}
            </ul>
            <p className="gd-foot">Every other module is in the left navigation, or search with <strong>All modules</strong>.</p>
          </section>
        </aside>
      </div>
    </div>
  );
}
