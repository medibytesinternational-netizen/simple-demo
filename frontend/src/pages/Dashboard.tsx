import { useEffect, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "../api";
import type { Alert, AppTask, DocumentSummary, Draft, InvestigationRequest, Meta } from "../types";
import { DEMO_MODE } from "../demo/config";
import { AlertQualityTable } from "../features/f14/AlertQualityTable";
import type { F14Dashboard, F14Row } from "../features/f14/types";
import { HalfGauge, PillBars } from "../components/charts";
import { Icon } from "../components/icons";
import { useOpenChart } from "../components/openChart";
import { WARDS } from "../components/wards";
import { Banner, Disclosure, EmptyState, Skeleton } from "../components/ui";

type Row = F14Row;
type Referral = { id: string; specialty: string; status: string };

// Only the primary synthetic patient has a full clinical chart in the current data.
const CHART_PATIENT_ID = "pat_ravi";
const openChartAvailable = (row: Row) => row.browsable ?? row.patient_id === CHART_PATIENT_ID;
const PENDING_DRAFT = new Set(["draft_ready", "human_edited", "model_unavailable"]);
const ATTENTION_LIMIT = 5;
// Draft-producing modules; the hospital view only counts them; review happens inside the patient.
const DRAFT_FEATURES = ["F1", "F2", "F3", "F4", "F7", "F11", "F6", "F9", "F10"];

type Attention = {
  key: string;
  tone: "critical" | "warning" | "info";
  tag: string;
  title: string;
  detail: string;
  patient?: Row;
  rank: number;
};

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const place = (r?: Row) => (r ? [r.ward, r.bed].filter(Boolean).join(" · ") : "");
const initials = (name: string) => name.split(" ").map((part) => part[0]).join("").slice(0, 2).toUpperCase();

function overdueBy(due: string | null | undefined, now?: string) {
  if (!due || !now) return "";
  const minutes = Math.round((Date.parse(now) - Date.parse(due)) / 60000);
  if (minutes <= 0) return "";
  return minutes < 60 ? `${minutes} min overdue` : `${Math.round(minutes / 60)} h overdue`;
}

function patientStatus(row: Row): { tone: "neutral" | "critical" | "warning" | "info" | "success"; text: string } {
  if (row.encounter_status === "discharged") return { tone: "neutral", text: "Discharged" };
  if (row.critical_alerts) return { tone: "critical", text: "Critical" };
  if (row.overdue_tasks) return { tone: "warning", text: "Task overdue" };
  if (row.open_alerts) return { tone: "warning", text: "Alert" };
  if (row.pending_drafts) return { tone: "info", text: "Review" };
  return { tone: "success", text: "Stable" };
}

export function DashboardPage() {
  const [clockNow, setClockNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setClockNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const openChart = useOpenChart();
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta") });
  const dashboard = useQuery<F14Dashboard>({ queryKey: ["hospital-dashboard"], queryFn: () => get("/hospital/dashboard") });
  const alerts = useQuery<{ alerts: Alert[] }>({ queryKey: ["alerts"], queryFn: () => get("/alerts") });
  const tasks = useQuery<{ tasks: AppTask[] }>({ queryKey: ["tasks"], queryFn: () => get("/tasks") });
  const documents = useQuery<{ documents: DocumentSummary[] }>({ queryKey: ["documents"], queryFn: () => get("/documents") });
  const referrals = useQuery<{ referrals: Referral[] }>({ queryKey: ["referrals"], queryFn: () => get("/referrals") });
  const requests = useQuery<{ requests: InvestigationRequest[] }>({ queryKey: ["investigation-requests"], queryFn: () => get("/investigation-requests") });
  const drafts = useQueries({
    queries: DRAFT_FEATURES.map((feature) => ({ queryKey: ["drafts", feature], queryFn: () => get<{ drafts: Draft[] }>(`/drafts?feature=${feature}&limit=1`) })),
  });

  const now = meta.data?.demo_now;
  const data = dashboard.data;
  const summary = data?.summary;
  const rows = data?.patients || [];
  const primary = rows.find((row) => row.patient_id === CHART_PATIENT_ID);
  const firstCritical = (alerts.data?.alerts || []).find((alert) => alert.status === "open" && alert.severity === "critical");
  const draftsPending = DRAFT_FEATURES.filter((_, i) => drafts[i].data?.drafts?.some((draft) => PENDING_DRAFT.has(draft.status))).length;
  const pendingDraftCount = (summary?.pending_drafts ?? 0) || draftsPending;

  // Opening a patient is the only way into clinical tabs from here.
  const openPatient = (row?: Row) => {
    if (!row) return null;
    return openChartAvailable(row)
      ? { label: "Open patient", onClick: () => openChart(row.patient_id) }
      : { label: "View summary", to: `/patients?patient=${encodeURIComponent(row.patient_id)}` };
  };

  // ---------- Needs attention: one row per patient problem, hospital-wide ----------
  const attention: Attention[] = [];
  rows.filter((row) => row.encounter_status !== "discharged").forEach((row) => {
    const isPrimary = row.patient_id === CHART_PATIENT_ID;
    if (row.critical_alerts) {
      attention.push({
        key: `critical-${row.patient_id}`, tone: "critical", tag: "Critical", rank: 0, patient: row,
        title: plural(row.critical_alerts, "critical alert"),
        detail: [isPrimary && firstCritical ? firstCritical.title : `${plural(row.open_alerts, "alert")} open`, row.overdue_tasks ? plural(row.overdue_tasks, "overdue task") : ""].filter(Boolean).join(" · "),
      });
    } else if (row.overdue_tasks) {
      const overdueTask = isPrimary ? (tasks.data?.tasks || []).find((task) => task.is_overdue && !["completed", "cancelled"].includes(task.status)) : undefined;
      attention.push({
        key: `overdue-${row.patient_id}`, tone: "warning", tag: "Overdue", rank: 1, patient: row,
        title: plural(row.overdue_tasks, "overdue task"),
        detail: overdueTask ? [overdueBy(overdueTask.due_at, now), overdueTask.title].filter(Boolean).join(" · ") : `${plural(row.open_alerts, "alert")} open`,
      });
    } else if (row.open_alerts) {
      attention.push({
        key: `alerts-${row.patient_id}`, tone: "warning", tag: "Check", rank: 2, patient: row,
        title: plural(row.open_alerts, "alert") + " to check", detail: `${plural(row.pending_tasks, "task")} pending`,
      });
    }
  });
  if (primary && (summary?.pending_documents || 0) > 0) {
    const doc = (documents.data?.documents || []).find((item) => ["needs_confirmation", "pending", "needs_manual_entry"].includes(item.ocr_status));
    attention.push({
      key: "documents", tone: "info", tag: "Confirm", rank: 3, patient: primary,
      title: `${plural(summary?.pending_documents || 1, "report")} to confirm`,
      detail: doc ? `${doc.filename} · read automatically, check before use` : "A person must confirm the values",
    });
  }
  if (primary && pendingDraftCount) {
    attention.push({
      key: "drafts", tone: "info", tag: "Review", rank: 4, patient: primary,
      title: `${plural(pendingDraftCount, "MediBytes Analysis")} awaiting review`, detail: "Not part of the record until a clinician approves it",
    });
  }
  attention.sort((a, b) => a.rank - b.rank || (b.patient?.critical_alerts ?? 0) - (a.patient?.critical_alerts ?? 0));
  const shown = attention.slice(0, ATTENTION_LIMIT);
  const next = attention[0];
  const nextAction = openPatient(next?.patient);

  // ---------- Patients by urgency ----------
  const urgency = (row: Row) => row.critical_alerts * 100 + row.open_alerts * 10 + row.overdue_tasks + (row.encounter_status === "discharged" ? -1000 : 0);
  const patients = [...rows].sort((a, b) => urgency(b) - urgency(a) || a.name.localeCompare(b.name));

  // ---------- Wards: occupied = active encounters; capacity = configured bed list ----------
  const occupied = summary?.wards || {};
  const wards = WARDS.map((ward) => ({ name: ward.name, used: occupied[ward.name] || 0, total: ward.beds.length }));
  const totalUsed = wards.reduce((sum, ward) => sum + ward.used, 0);
  const totalBeds = wards.reduce((sum, ward) => sum + ward.total, 0);
  const freeBeds = totalBeds - totalUsed;
  const busiest = [...wards].sort((a, b) => b.used / b.total - a.used / a.total)[0];
  const shades = ["accent", "deep", "soft"] as const;

  // ---------- KPIs, hospital-wide ----------
  const kpis = summary ? [
    { key: "patients", label: "Patients in care", value: summary.active_encounters, note: `${summary.patients} on record`, feature: true, to: "/patients" },
    { key: "critical", label: "Critical alerts", value: summary.critical_alerts, note: `${summary.open_alerts} alerts open`, tone: "critical" },
    { key: "overdue", label: "Overdue tasks", value: summary.overdue_tasks, note: `${summary.escalated_tasks} escalated`, tone: "warning" },
    { key: "beds", label: "Free beds", value: freeBeds, note: `of ${totalBeds} configured beds`, to: "/admission" },
  ] : [];

  // ---------- Pending work, hospital-wide (counts only) ----------
  const referralCount = (referrals.data?.referrals || []).filter((item) => ["sent", "acknowledged"].includes(item.status)).length;
  const requestCount = (requests.data?.requests || []).filter((item) => item.status === "approved").length;
  const pending = summary ? [
    { key: "notes", label: "MediBytes Analysis to review", value: pendingDraftCount, note: "Not yet approved", tone: "info" },
    { key: "documents", label: "Reports to confirm", value: summary.pending_documents, note: "OCR values need a person", tone: "info" },
    { key: "referrals", label: "Referrals awaiting reply", value: referralCount || summary.open_referrals, note: "Sent or acknowledged" },
    { key: "requests", label: "Investigations", value: requestCount || summary.pending_investigations, note: "Approved requests" },
    { key: "discharge", label: "Discharges to sign", value: summary.discharge_reviews, note: summary.draft_discharges ? `${summary.draft_discharges} drafts` : "Reviewed, unsigned" },
    { key: "meds", label: "Medicine differences", value: summary.medicine_discrepancies, note: "Home vs inpatient", tone: summary.medicine_discrepancies ? "warning" : undefined },
  ] : [];

  const today = clockNow.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const time = clockNow.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const detailsLoading = [alerts, tasks, documents].some((query) => query.isLoading);

  return (
    <div className="page dk-page pg-dashboard">
      <header className="dk-head">
        <div>
          <h1 className="dk-title">Hospital dashboard</h1>
          <p className="dk-sub">What needs attention across the hospital today. Open a patient to act.</p>
        </div>
        <div className="dk-actions">
          <Link className="dk-btn dk-btn-primary" to="/admission"><Icon name="plus" size={16} /> New admission</Link>
          <Link className="dk-btn dk-btn-outline" to="/patients"><Icon name="patients" size={16} /> Patient list</Link>
        </div>
      </header>

      {dashboard.isError ? (
        <Banner tone="danger" role="alert" actions={<button className="btn btn-sm" onClick={() => dashboard.refetch()}>Try again</button>}>
          The hospital dashboard could not be loaded. {(dashboard.error as Error).message}
        </Banner>
      ) : null}

      <section className="dk-kpis" aria-label="Hospital at a glance">
        {summary ? kpis.map((kpi) => {
          const body = (
            <>
              <span className="dk-kpi-label">{kpi.label}</span>
              {kpi.to ? <span className="dk-kpi-arrow" aria-hidden="true"><Icon name="arrow" size={15} /></span> : null}
              <span className="dk-kpi-value">{kpi.value}</span>
              <span className="dk-kpi-note">{kpi.note}</span>
            </>
          );
          const cls = `dk-kpi ${kpi.feature ? "is-feature" : ""} ${kpi.tone ? `tone-${kpi.tone}` : ""}`;
          return kpi.to
            ? <Link key={kpi.key} to={kpi.to} className={cls} aria-label={`${kpi.label}: ${kpi.value}. ${kpi.note}.`}>{body}</Link>
            : <div key={kpi.key} className={cls}>{body}</div>;
        }) : Array.from({ length: 4 }, (_, i) => (
          <div className="dk-kpi" key={i} aria-busy="true" aria-label="Loading hospital totals"><Skeleton count={3} /></div>
        ))}
      </section>

      <div className="dk-grid">
        <section className="dk-card span-5" aria-labelledby="dk-wards">
          <div className="dk-card-head">
            <div>
              <h2 className="dk-card-title" id="dk-wards">Ward occupancy</h2>
              <p className="dk-card-sub">{data ? `${totalUsed} of ${totalBeds} beds in use · ${freeBeds} free` : "Loading beds"}</p>
            </div>
          </div>
          {data ? (
            <PillBars
              ariaLabel="Beds occupied per ward"
              highlight={busiest?.used ? busiest.name : undefined}
              items={wards.map((ward, i) => ({
                key: ward.name, label: ward.name, valueText: `${ward.used}/${ward.total}`, share: ward.total ? ward.used / ward.total : 0,
                tone: ward.used >= ward.total ? "critical" : shades[i % shades.length],
                detail: `${ward.total - ward.used} beds free`,
              }))}
            />
          ) : <Skeleton count={4} />}
          <p className="dk-card-foot">Filled: beds with an active admission. Hatched: free beds from the admission bed list.</p>
        </section>

        <section className="dk-card dk-reminder span-3" aria-labelledby="dk-next">
          <div className="dk-card-head"><h2 className="dk-card-title" id="dk-next">Next up</h2></div>
          {dashboard.isLoading || (data && detailsLoading && !next) ? <Skeleton count={3} /> : next ? (
            <>
              <div className="dk-reminder-body">
                <p className="dk-reminder-title">{next.title}</p>
                {next.patient ? <div className="dk-reminder-meta"><strong>{next.patient.name}</strong>{place(next.patient) ? ` · ${place(next.patient)}` : ""}</div> : null}
                <p className="dk-reminder-detail">{next.detail}</p>
              </div>
              {nextAction?.onClick ? (
                <button type="button" className="dk-btn dk-btn-primary" onClick={nextAction.onClick}><Icon name="user" size={16} /> {nextAction.label}</button>
              ) : nextAction?.to ? (
                <Link className="dk-btn dk-btn-primary" to={nextAction.to}><Icon name="user" size={16} /> {nextAction.label}</Link>
              ) : null}
            </>
          ) : (
            <EmptyState icon="check" title="Nothing urgent right now" />
          )}
        </section>

        <section className="dk-card span-4" aria-labelledby="dk-patients">
          <div className="dk-card-head">
            <h2 className="dk-card-title" id="dk-patients">Patients</h2>
            <Link className="dk-btn dk-btn-outline dk-btn-sm" to="/patients">View all</Link>
          </div>
          {dashboard.isLoading ? <Skeleton variant="rows" count={5} /> : patients.length ? (
            <ul className="dk-list">
              {patients.slice(0, 5).map((row) => {
                const status = patientStatus(row);
                const action = openPatient(row)!;
                const body = (
                  <>
                    <span className={`dk-item-icon ${row.encounter_status === "discharged" ? "tone-muted" : ""}`} aria-hidden="true">{initials(row.name)}</span>
                    <span className="dk-item-text">
                      <span className="dk-item-title">{row.name}</span>
                      <span className="dk-item-meta">{row.mrn}{place(row) ? ` · ${place(row)}` : ""}</span>
                    </span>
                  </>
                );
                return (
                  <li key={row.patient_id}>
                    {action.onClick
                      ? <button type="button" className="dk-item" onClick={action.onClick} aria-label={`${action.label}: ${row.name}, ${status.text}`}>{body}</button>
                      : <Link className="dk-item" to={action.to!} aria-label={`${action.label}: ${row.name}, ${status.text}`}>{body}</Link>}
                  </li>
                );
              })}
            </ul>
          ) : <EmptyState icon="patients" title="No patients on record" />}
        </section>

        <section className="dk-card span-5" aria-labelledby="dk-attention">
          <div className="dk-card-head">
            <div>
              <h2 className="dk-card-title" id="dk-attention">Needs attention</h2>
              <p className="dk-card-sub">{attention.length ? `${shown.length} of ${attention.length} · open the patient to act` : "Hospital overview"}</p>
            </div>
          </div>
          {dashboard.isLoading || (data && detailsLoading && !attention.length) ? <Skeleton variant="rows" count={4} /> : null}
          {data && !detailsLoading && !attention.length ? (
            <EmptyState icon="check" title="Nothing needs attention right now">New critical alerts, overdue tasks and reports to confirm appear here.</EmptyState>
          ) : null}
          {shown.length ? (
            <ul className="dk-list">
              {shown.map((item) => {
                const action = openPatient(item.patient);
                const body = (
                  <>
                    <span className={`dk-item-icon tone-${item.tone}`} aria-hidden="true">{item.patient ? initials(item.patient.name) : "!"}</span>
                    <span className="dk-item-text">
                      <span className="dk-item-title">{item.patient?.name || item.title}</span>
                      <span className="dk-item-meta"><strong>{item.title}</strong>{item.detail ? ` · ${item.detail}` : ""}</span>
                    </span>
                    <span className={`dk-tag tone-${item.tone}`}>{item.tag}</span>
                  </>
                );
                return (
                  <li key={item.key}>
                    {action?.onClick
                      ? <button type="button" className="dk-item" onClick={action.onClick}>{body}</button>
                      : action?.to ? <Link className="dk-item" to={action.to}>{body}</Link>
                      : <div className="dk-item">{body}</div>}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </section>

        <section className="dk-card span-4" aria-labelledby="dk-beds">
          <div className="dk-card-head"><h2 className="dk-card-title" id="dk-beds">Bed occupancy</h2></div>
          {data ? (
            <HalfGauge
              value={totalUsed} max={totalBeds} label="Bed occupancy"
              caption={`${totalUsed} of ${totalBeds} beds in use`}
              segments={[{ key: "used", label: "Occupied", value: totalUsed, tone: "fill" }, { key: "free", label: "Free", value: freeBeds, tone: "hatch" }]}
            />
          ) : <Skeleton count={4} />}
        </section>

        <section className="dk-card dk-dark span-3" aria-labelledby="dk-clock">
          <div className="dk-card-head">
            <div>
              <h2 className="dk-card-title" id="dk-clock">Hospital clock</h2>
              <p className="dk-card-sub">Current local time</p>
            </div>
          </div>
          <div className="dk-clock" aria-live="off">{time || "--:--"}</div>
          <div className="dk-clock-date">{today || "Loading"}</div>
          <p className="dk-card-foot">Current local time from this device.</p>
        </section>

        <section className="dk-card span-12" aria-labelledby="dk-pending">
          <div className="dk-card-head">
            <div>
              <h2 className="dk-card-title" id="dk-pending">Pending work across the hospital</h2>
              <p className="dk-card-sub">Exact counts from the hospital summary. Open a patient to work on them.</p>
            </div>
          </div>
          {summary ? (
            <div className="dk-stats">
              {pending.map((item) => (
                <div key={item.key} className={`dk-stat ${item.tone ? `tone-${item.tone}` : ""}`}>
                  <span className="dk-stat-value">{item.value}</span>
                  <span className="dk-stat-label">{item.label}</span>
                  <span className="dk-stat-note">{item.note}</span>
                </div>
              ))}
            </div>
          ) : <Skeleton count={2} />}
        </section>
      </div>

      {/* F14 alert quality: live backend only (not in the preview fixtures). */}
      {DEMO_MODE ? null : (
        <Disclosure title="Alert quality (optional details)">
          <AlertQualityTable />
        </Disclosure>
      )}
    </div>
  );
}
