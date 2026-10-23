import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "../api";
import type { Alert, AppTask, DocumentSummary, Draft, InvestigationRequest, Meta } from "../types";
import { DEMO_MODE } from "../demo/config";
import { AlertQualityTable } from "../features/f14/AlertQualityTable";
import type { F14Dashboard, F14Row } from "../features/f14/types";
import { Icon } from "../components/icons";
import { useOpenChart } from "../components/openChart";
import { WARDS } from "../components/wards";
import "./dashboard.css";

type Row = F14Row;
type Tone = "critical" | "warning" | "info" | "neutral";
type Referral = { id: string; specialty: string; status: string };

// Only the primary synthetic patient has a full clinical chart in the current data.
const CHART_PATIENT_ID = "pat_ravi";
// The backend marks each row `browsable`; preview fixtures predate the flag, so fall back to the chart patient.
const opensChart = (row: Row) => row.browsable ?? row.patient_id === CHART_PATIENT_ID;
const PENDING_DRAFT = new Set(["draft_ready", "human_edited", "model_unavailable"]);
const ATTENTION_LIMIT = 5;

// Draft-producing modules and the existing screen where each draft is reviewed.
const DRAFT_SCREENS = [
  { feature: "F1", label: "consultation note", to: "/notes?tab=consult" },
  { feature: "F2", label: "admission assessment", to: "/notes?tab=admission" },
  { feature: "F3", label: "ward round note", to: "/notes?tab=round" },
  { feature: "F4", label: "progress note", to: "/notes?tab=progress" },
  { feature: "F7", label: "ICU flow sheet", to: "/notes?tab=icu" },
  { feature: "F11", label: "referral letter", to: "/notes?tab=referral" },
  { feature: "F6", label: "medication reconciliation", to: "/safety?tab=meds" },
  { feature: "F9", label: "discharge summary", to: "/discharge" },
  { feature: "F10", label: "investigation request", to: "/documents?tab=requisition" },
];

type Attention = { key: string; tone: Tone; icon: string; title: string; detail: string; patient?: Row; to: string; rank: number };

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const place = (r?: Row) => (r ? [r.ward, r.bed].filter(Boolean).join(" · ") : "");
const initials = (name: string) => name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();

function overdueBy(due: string | null | undefined, now?: string) {
  if (!due || !now) return "";
  const minutes = Math.round((Date.parse(now) - Date.parse(due)) / 60000);
  if (minutes <= 0) return "";
  return minutes < 60 ? `${minutes} min overdue` : `${Math.round(minutes / 60)} h overdue`;
}

export function DashboardPage() {
  const openChart = useOpenChart();
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta") });
  const dashboard = useQuery<F14Dashboard>({ queryKey: ["hospital-dashboard"], queryFn: () => get("/hospital/dashboard") });
  const alerts = useQuery<{ alerts: Alert[] }>({ queryKey: ["alerts"], queryFn: () => get("/alerts") });
  const tasks = useQuery<{ tasks: AppTask[] }>({ queryKey: ["tasks"], queryFn: () => get("/tasks") });
  const documents = useQuery<{ documents: DocumentSummary[] }>({ queryKey: ["documents"], queryFn: () => get("/documents") });
  const referrals = useQuery<{ referrals: Referral[] }>({ queryKey: ["referrals"], queryFn: () => get("/referrals") });
  const requests = useQuery<{ requests: InvestigationRequest[] }>({ queryKey: ["investigation-requests"], queryFn: () => get("/investigation-requests") });
  const drafts = useQueries({
    queries: DRAFT_SCREENS.map((d) => ({ queryKey: ["drafts", d.feature], queryFn: () => get<{ drafts: Draft[] }>(`/drafts?feature=${d.feature}&limit=1`) })),
  });

  const now = meta.data?.demo_now;
  const data = dashboard.data;
  const summary = data?.summary;
  const rows = data?.patients || [];
  const byId = new Map(rows.map((r) => [r.patient_id, r]));
  const primary = byId.get(CHART_PATIENT_ID);
  const firstDraft = DRAFT_SCREENS.find((_, i) => drafts[i].data?.drafts?.some((x) => PENDING_DRAFT.has(x.status)));

  // ---------- Needs attention: built only from existing records, one row per problem ----------
  const attention: Attention[] = [];
  if (primary) {
    const open = (alerts.data?.alerts || []).filter((a) => a.status === "open");
    const critical = open.filter((a) => a.severity === "critical");
    if (critical.length) {
      attention.push({
        key: "primary-critical", tone: "critical", icon: "alert", rank: 0, patient: primary, to: "/safety?tab=alerts",
        title: critical.length === 1 ? critical[0].title : `${plural(critical.length, "critical safety alert")}`,
        detail: critical.length === 1 ? "Critical safety alert" : `Includes: ${critical[0].title}`,
      });
    }
    (tasks.data?.tasks || []).filter((t) => t.is_overdue && !["completed", "cancelled"].includes(t.status)).forEach((t) => attention.push({
      key: `task-${t.id}`, tone: "warning", icon: "clock", rank: 1, patient: primary, to: "/tasks", title: t.title,
      detail: [overdueBy(t.due_at, now) || "Overdue", t.escalation_level ? "escalated" : "", t.owner ? `assigned to ${t.owner}` : ""].filter(Boolean).join(" · "),
    }));
    const warnings = open.filter((a) => a.severity !== "critical");
    if (warnings.length) {
      attention.push({
        key: "primary-warnings", tone: "warning", icon: "alert", rank: 2, patient: primary, to: "/safety?tab=alerts",
        title: warnings.length === 1 ? warnings[0].title : `${plural(warnings.length, "alert")} to check`,
        detail: warnings.length === 1 ? "Lower-priority safety alert" : `Includes: ${warnings[0].title}`,
      });
    }
    (documents.data?.documents || []).filter((d) => d.ocr_status === "needs_confirmation" || d.ocr_status === "pending").forEach((d) => attention.push({
      key: `doc-${d.id}`, tone: "info", icon: "scan", rank: 3, patient: primary, to: "/documents?tab=inbound",
      title: "Report values need confirmation", detail: `${d.filename} · read automatically, check before use`,
    }));
  }
  rows.filter((r) => r.patient_id !== CHART_PATIENT_ID && r.encounter_status !== "discharged" && (r.open_alerts || r.overdue_tasks)).forEach((r) => {
    const critical = r.critical_alerts > 0;
    // A patient with only non-critical alerts (no overdue task) is titled by its alerts, never "0 overdue tasks".
    const titleIcon = critical ? "alert" : r.overdue_tasks ? "clock" : "alert";
    attention.push({
      key: `cohort-${r.patient_id}`, tone: critical ? "critical" : "warning", icon: titleIcon, rank: critical ? 0.5 : 1.5, patient: r,
      to: `/patients?patient=${encodeURIComponent(r.patient_id)}`,
      title: critical ? plural(r.critical_alerts, "critical alert") : r.overdue_tasks ? plural(r.overdue_tasks, "overdue task") : `${plural(r.open_alerts, "alert")} to check`,
      detail: [r.overdue_tasks && critical ? plural(r.overdue_tasks, "overdue task") : "", r.escalated_tasks ? "escalated" : "", "summary record"].filter(Boolean).join(" · "),
    });
  });
  const pendingDraftCount = DRAFT_SCREENS.filter((_, i) => drafts[i].data?.drafts?.some((x) => PENDING_DRAFT.has(x.status))).length;
  if (pendingDraftCount && firstDraft) {
    attention.push({
      key: "drafts", tone: "info", icon: "progress", rank: 4, to: firstDraft.to,
      title: `${plural(pendingDraftCount, "AI-written draft")} awaiting review`, detail: "Not part of the record until a clinician approves",
    });
  }
  attention.sort((a, b) => a.rank - b.rank);
  const shown = attention.slice(0, ATTENTION_LIMIT);
  const detailsLoading = [alerts, tasks, documents].some((q) => q.isLoading);

  // ---------- Patients (most urgent first) ----------
  const urgency = (r: Row) => r.critical_alerts * 100 + r.open_alerts * 10 + r.overdue_tasks + (r.encounter_status === "discharged" ? -1000 : 0);
  const patients = [...rows].sort((a, b) => urgency(b) - urgency(a) || a.name.localeCompare(b.name));

  // ---------- Wards: occupied = active encounters; capacity = configured bed list ----------
  const occupied = summary?.wards || {};
  const wards = WARDS.map((w) => ({ name: w.name, used: occupied[w.name] || 0, total: w.beds.length }));
  const unconfigured = Object.keys(occupied).filter((name) => !WARDS.some((w) => w.name === name));
  const totalUsed = wards.reduce((n, w) => n + w.used, 0);
  const totalBeds = wards.reduce((n, w) => n + w.total, 0);

  const indicators = summary ? [
    { key: "patients", icon: "patients", tone: "info", value: summary.active_encounters, label: "Patients in care", note: `of ${summary.patients} on record`, to: "/patients" },
    { key: "critical", icon: "safety", tone: summary.critical_alerts ? "critical" : "neutral", value: summary.critical_alerts, label: "Critical alerts", note: `${summary.open_alerts} alerts open`, to: "/safety?tab=alerts" },
    { key: "overdue", icon: "clock", tone: summary.overdue_tasks ? "warning" : "neutral", value: summary.overdue_tasks, label: "Overdue tasks", note: summary.escalated_tasks ? `${summary.escalated_tasks} escalated` : "none escalated", to: "/tasks" },
    { key: "notes", icon: "chart", tone: "info", value: summary.pending_drafts, label: "Notes to review", note: "AI drafts, not yet approved", to: firstDraft?.to || "/notes" },
  ] : [];

  const pending = summary ? [
    { label: "Reports to confirm", value: summary.pending_documents, to: "/documents?tab=inbound", icon: "scan" },
    { label: "Referrals awaiting reply", value: (referrals.data?.referrals || []).filter((r) => r.status === "sent" || r.status === "acknowledged").length || summary.open_referrals, to: "/notes?tab=referral", icon: "referral" },
    { label: "Investigation requests", value: (requests.data?.requests || []).filter((r) => r.status === "approved").length || summary.pending_investigations, to: "/documents?tab=requisition", icon: "request" },
    { label: "Discharge summaries to sign", value: summary.discharge_reviews, to: "/discharge", icon: "discharge" },
    // F14 counts from the current backend; the preview fixtures predate them, so absent rows are left out.
    { label: "Pending tasks", value: summary.pending_tasks, to: "/tasks", icon: "tasks" },
    { label: "Draft discharges to review", value: summary.draft_discharges, to: "/discharge", icon: "discharge" },
    { label: "Medicine discrepancies", value: summary.medicine_discrepancies, to: "/safety?tab=meds", icon: "pill" },
    { label: "Claim gaps", value: summary.claim_gaps, to: "/revenue?tab=claim", icon: "billing" },
  ].filter((p) => p.value !== undefined) : [];

  const today = now ? new Date(now).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" }) : null;
  const time = now ? new Date(now).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : null;

  return (
    <div className="hd">
      {/* 1 · Header */}
      <header className="hd-head">
        <div>
          <h1 className="hd-title">Hospital Overview</h1>
          <p className="hd-subtitle">A clear picture of today's hospital activity.</p>
        </div>
        {today ? <div className="hd-date" title="Demo clock"><Icon name="clock" size={16} /><span>{today}</span><span className="hd-date-time">{time}</span></div> : null}
      </header>

      {dashboard.isError ? (
        <div className="hd-error" role="alert">
          <Icon name="alert" size={18} />
          <span>The hospital overview could not be loaded. {(dashboard.error as Error).message}</span>
          <button className="btn btn-sm" onClick={() => dashboard.refetch()}>Try again</button>
        </div>
      ) : null}

      {/* 2 · Indicators */}
      <section className="hd-indicators" aria-label="Today at a glance">
        {indicators.length ? indicators.map((i) => (
          <Link key={i.key} to={i.to} className={`hd-ind tone-${i.tone}`}>
            <span className="hd-ind-icon" aria-hidden="true"><Icon name={i.icon} size={22} /></span>
            <span className="hd-ind-body">
              <span className="hd-ind-value">{i.value}</span>
              <span className="hd-ind-label">{i.label}</span>
              <span className="hd-ind-note">{i.note}</span>
            </span>
          </Link>
        )) : [0, 1, 2, 3].map((k) => <div key={k} className="hd-ind is-loading" aria-hidden="true" />)}
      </section>

      {/* 3 · Needs attention */}
      <section className="hd-section hd-attention" aria-labelledby="hd-attention-title">
        <div className="hd-section-head">
          <h2 id="hd-attention-title" className="hd-h2">Needs attention</h2>
          {attention.length ? <span className="hd-count">{shown.length} of {attention.length}</span> : null}
          <div className="hd-head-links">
            <Link to="/safety?tab=alerts">All alerts <Icon name="chevron" size={14} /></Link>
            <Link to="/tasks">All tasks <Icon name="chevron" size={14} /></Link>
          </div>
        </div>
        {dashboard.isLoading || (data && detailsLoading && !attention.length) ? <div className="hd-skeleton" aria-busy="true"><span /><span /><span /></div> : null}
        {data && !detailsLoading && !attention.length ? (
          <p className="hd-clear"><Icon name="check" size={18} /> Nothing needs attention right now.</p>
        ) : null}
        {shown.length ? (
          <ul className="hd-attn">
            {shown.map((a) => (
              <li key={a.key}>
                <Link to={a.to} className={`hd-attn-row tone-${a.tone}`}>
                  <span className="hd-attn-icon" aria-hidden="true"><Icon name={a.icon} size={17} /></span>
                  <span className="hd-attn-main">
                    <span className="hd-attn-title">{a.title}</span>
                    <span className="hd-attn-detail">{a.detail}</span>
                  </span>
                  <span className="hd-attn-patient">
                    {a.patient ? <><strong>{a.patient.name}</strong><span>{place(a.patient)}</span></> : <span>Hospital-wide</span>}
                  </span>
                  <Icon name="chevron" size={18} className="hd-chev" />
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {/* 4 + 5 · Wards and patients */}
      <div className="hd-split">
        <section className="hd-section" aria-labelledby="hd-patients-title">
          <div className="hd-section-head">
            <h2 id="hd-patients-title" className="hd-h2">Patients</h2>
            <div className="hd-head-links"><Link to="/patients">Patient list <Icon name="chevron" size={14} /></Link></div>
          </div>
          {dashboard.isLoading ? <div className="hd-skeleton"><span /><span /><span /></div> : null}
          {data && !patients.length ? <p className="hd-empty">No patients on record.</p> : null}
          <ul className="hd-patients">
            {patients.map((r) => {
              const discharged = r.encounter_status === "discharged";
              const status = discharged ? { tone: "neutral", text: "Discharged" }
                : r.critical_alerts ? { tone: "critical", text: "Critical alerts" }
                : r.overdue_tasks ? { tone: "warning", text: "Task overdue" }
                : r.open_alerts ? { tone: "warning", text: "Alert to check" }
                : r.pending_drafts ? { tone: "info", text: "Needs review" }
                : { tone: "ok", text: "Stable" };
              const chart = opensChart(r);
              return (
                <li key={r.patient_id} className={discharged ? "is-muted" : ""}>
                  <Link to={chart ? "/timeline" : `/patients?patient=${encodeURIComponent(r.patient_id)}`} className="hd-patient"
                    onClick={chart ? (event) => { event.preventDefault(); openChart(r.patient_id); } : undefined}
                    aria-label={`${r.name}, ${status.text}. ${chart ? "Open chart" : "View summary"}`}>
                    <span className="hd-avatar" aria-hidden="true">{initials(r.name)}</span>
                    <span className="hd-patient-id">
                      <strong>{r.name}</strong>
                      <span>{r.mrn}{place(r) ? ` · ${place(r)}` : ""}</span>
                    </span>
                    <span className={`hd-status tone-${status.tone}`}>{status.text}</span>
                    <span className="hd-open">{chart ? "Open chart" : "Summary"}<Icon name="chevron" size={16} /></span>
                  </Link>
                </li>
              );
            })}
          </ul>
          {data ? <p className="hd-foot">Full charts are available for {primary?.name || "the primary patient"} only; other patients have summary records.</p> : null}
        </section>

        <section className="hd-section" aria-labelledby="hd-wards-title">
          <div className="hd-section-head">
            <h2 id="hd-wards-title" className="hd-h2">Ward overview</h2>
            {data ? <span className="hd-count">{totalUsed} of {totalBeds} beds in use</span> : null}
          </div>
          {data ? (
            <ul className="hd-wards">
              {wards.map((w) => (
                <li key={w.name} className="hd-ward">
                  <span className="hd-ward-name">{w.name}</span>
                  <span className="hd-ward-nums"><strong>{w.used}</strong> / {w.total}</span>
                  <span className="hd-meter" role="img" aria-label={`${w.name}: ${w.used} of ${w.total} beds occupied, ${w.total - w.used} available`}>
                    <span style={{ width: `${(w.used / w.total) * 100}%` }} />
                  </span>
                  <span className="hd-ward-free">{w.total - w.used} available</span>
                </li>
              ))}
              {unconfigured.map((name) => (
                <li key={name} className="hd-ward">
                  <span className="hd-ward-name">{name}</span>
                  <span className="hd-ward-nums">{plural(occupied[name], "patient")}</span>
                  <span className="hd-ward-free">Bed capacity not configured</span>
                </li>
              ))}
            </ul>
          ) : dashboard.isLoading ? <div className="hd-skeleton"><span /><span /></div> : <p className="hd-empty">Ward data is unavailable.</p>}
          <p className="hd-foot">Occupied = active admissions. Totals come from the bed list used for admissions.</p>
        </section>
      </div>

      {/* 6 · Quick actions and pending work */}
      <div className="hd-split hd-split-even">
        <section className="hd-section" aria-labelledby="hd-actions-title">
          <div className="hd-section-head"><h2 id="hd-actions-title" className="hd-h2">Quick actions</h2></div>
          <div className="hd-actions">
            <Link className="hd-action" to="/admission"><Icon name="admission" size={18} />New admission</Link>
            <Link className="hd-action" to={firstDraft?.to || "/notes"}><Icon name="progress" size={18} />Review notes</Link>
            <Link className="hd-action" to="/tasks"><Icon name="tasks" size={18} />Open tasks</Link>
          </div>
        </section>

        <section className="hd-section" aria-labelledby="hd-pending-title">
          <div className="hd-section-head"><h2 id="hd-pending-title" className="hd-h2">Pending work</h2></div>
          {pending.length ? (
            <ul className="hd-pending">
              {pending.map((p) => (
                <li key={p.label}>
                  <Link to={p.to} className="hd-pending-row">
                    <Icon name={p.icon} size={17} className="hd-pending-icon" />
                    <span className="hd-pending-label">{p.label}</span>
                    <span className={`hd-pending-count ${p.value ? "" : "zero"}`}>{p.value}</span>
                    <Icon name="chevron" size={16} className="hd-chev" />
                  </Link>
                </li>
              ))}
            </ul>
          ) : <div className="hd-skeleton"><span /><span /></div>}
        </section>
      </div>

      {/* F14 alert quality: live backend only (not in the preview fixtures). */}
      {DEMO_MODE ? null : <div className="mt-3"><AlertQualityTable /></div>}
    </div>
  );
}
