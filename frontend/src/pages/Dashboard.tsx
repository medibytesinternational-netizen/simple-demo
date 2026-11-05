import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "../api";
import type { Alert, AppTask, DocumentSummary, Draft, InvestigationRequest, Meta } from "../types";
import { DEMO_MODE } from "../demo/config";
import { AlertQualityTable } from "../features/f14/AlertQualityTable";
import type { F14Dashboard, F14Row } from "../features/f14/types";
import { useOpenChart } from "../components/openChart";
import { WARDS } from "../components/wards";
import { Banner, Disclosure, Skeleton } from "../components/ui";

type Row = F14Row;
type Referral = { id: string; specialty: string; status: string };

// Only the primary synthetic patient has a full clinical chart in the current data.
const CHART_PATIENT_ID = "pat_ravi";
const openChartAvailable = (row: Row) => row.browsable ?? row.patient_id === CHART_PATIENT_ID;
const PENDING_DRAFT = new Set(["draft_ready", "human_edited", "model_unavailable"]);
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

  // ---------- Patients by urgency ----------
  const urgency = (row: Row) => row.critical_alerts * 100 + row.open_alerts * 10 + row.overdue_tasks + (row.encounter_status === "discharged" ? -1000 : 0);
  const patients = [...rows].sort((a, b) => urgency(b) - urgency(a) || a.name.localeCompare(b.name));

  // ---------- Wards: occupied = active encounters; capacity = configured bed list ----------
  const occupied = summary?.wards || {};
  const wards = WARDS.map((ward) => ({ name: ward.name, used: occupied[ward.name] || 0, total: ward.beds.length }));
  const totalUsed = wards.reduce((sum, ward) => sum + ward.used, 0);
  const totalBeds = wards.reduce((sum, ward) => sum + ward.total, 0);
  const freeBeds = totalBeds - totalUsed;

  // ---------- KPIs, hospital-wide ----------
  const kpis = summary ? [
    { key: "patients", label: "Patients in care", value: summary.active_encounters, note: `${summary.patients} on record`, feature: true, to: "/patients" },
    { key: "critical", label: "Critical alerts", value: summary.critical_alerts, note: `${summary.open_alerts} alerts open`, tone: "critical" },
    { key: "overdue", label: "Overdue tasks", value: summary.overdue_tasks, note: `${summary.escalated_tasks} escalated`, tone: "warning" },
    { key: "beds", label: "Free beds", value: freeBeds, note: `of ${totalBeds} configured beds` },
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

  const detailsLoading = [alerts, tasks, documents].some((query) => query.isLoading);
  const counts: { key: string; label: string; value: number; note: string; tone?: string; to?: string }[] = [...kpis, ...pending];

  return (
    <div className="page his-dash">
      <header className="page-header">
        <div className="page-header-text">
          <h1 className="page-h1">Hospital Dashboard</h1>
          <p className="page-desc">What needs attention across the hospital today. Open a patient to act.</p>
        </div>
        <div className="page-header-actions button-row">
          <Link className="btn" to="/patients">Patient list</Link>
        </div>
      </header>

      {dashboard.isError ? (
        <Banner tone="danger" role="alert" actions={<button className="btn btn-sm" onClick={() => dashboard.refetch()}>Try again</button>}>
          The hospital dashboard could not be loaded. {(dashboard.error as Error).message}
        </Banner>
      ) : null}

      <div className="his-dash-cols">
        <section className="his-box">
          <h2 className="his-box-title">Hospital summary</h2>
          {summary ? (
            <table className="table">
              <thead><tr><th>Item</th><th className="right">Count</th><th>Note</th></tr></thead>
              <tbody>
                {counts.map((c) => (
                  <tr key={c.key}>
                    <td>{c.to ? <Link to={c.to}>{c.label}</Link> : c.label}</td>
                    <td className={`right strong ${c.tone && c.value ? `his-tone-${c.tone}` : ""}`}>{c.value}</td>
                    <td className="muted">{c.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Skeleton count={6} />}
        </section>

        <section className="his-box">
          <h2 className="his-box-title">Ward occupancy {data ? `(${totalUsed} of ${totalBeds} beds in use)` : ""}</h2>
          {data ? (
            <table className="table">
              <thead><tr><th>Ward</th><th className="right">Occupied</th><th className="right">Total</th><th className="right">Free</th></tr></thead>
              <tbody>
                {wards.map((w) => (
                  <tr key={w.name}>
                    <td>{w.name}</td>
                    <td className="right">{w.used}</td>
                    <td className="right">{w.total}</td>
                    <td className={`right ${w.used >= w.total ? "his-tone-critical strong" : ""}`}>{w.total - w.used}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Skeleton count={4} />}
        </section>
      </div>

      <section className="his-box">
        <h2 className="his-box-title">Needs attention</h2>
        {dashboard.isLoading || (data && detailsLoading && !attention.length) ? <Skeleton variant="rows" count={3} /> : attention.length ? (
          <table className="table">
            <thead><tr><th>Patient</th><th>Ward / Bed</th><th>Type</th><th>Issue</th><th>Detail</th><th /></tr></thead>
            <tbody>
              {attention.map((item) => {
                const action = openPatient(item.patient);
                return (
                  <tr key={item.key}>
                    <td>{item.patient?.name || "-"}</td>
                    <td>{place(item.patient) || "-"}</td>
                    <td className={`strong his-tone-${item.tone}`}>{item.tag}</td>
                    <td>{item.title}</td>
                    <td className="muted">{item.detail}</td>
                    <td className="right">
                      {action?.onClick ? <button type="button" className="btn btn-sm" onClick={action.onClick}>{action.label}</button>
                        : action?.to ? <Link className="btn btn-sm" to={action.to}>{action.label}</Link> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : <p className="his-box-empty">Nothing needs attention right now.</p>}
      </section>

      <section className="his-box">
        <h2 className="his-box-title">Patients</h2>
        {dashboard.isLoading ? <Skeleton variant="rows" count={5} /> : patients.length ? (
          <table className="table">
            <thead><tr><th>MRN</th><th>Name</th><th>Ward / Bed</th><th>Status</th><th className="right">Alerts</th><th className="right">Overdue</th><th /></tr></thead>
            <tbody>
              {patients.map((row) => {
                const status = patientStatus(row);
                const action = openPatient(row)!;
                return (
                  <tr key={row.patient_id}>
                    <td className="mono">{row.mrn}</td>
                    <td>{row.name}</td>
                    <td>{place(row) || "-"}</td>
                    <td className={`strong his-tone-${status.tone}`}>{status.text}</td>
                    <td className="right">{row.open_alerts}</td>
                    <td className="right">{row.overdue_tasks}</td>
                    <td className="right">
                      {action.onClick ? <button type="button" className="btn btn-sm" onClick={action.onClick}>{action.label}</button>
                        : <Link className="btn btn-sm" to={action.to!}>{action.label}</Link>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : <p className="his-box-empty">No patients on record.</p>}
      </section>

      {/* F14 alert quality: live backend only (not in the preview fixtures). */}
      {DEMO_MODE ? null : (
        <Disclosure title="Alert quality (optional details)">
          <AlertQualityTable />
        </Disclosure>
      )}
    </div>
  );
}
