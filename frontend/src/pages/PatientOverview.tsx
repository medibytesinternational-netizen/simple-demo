import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "../api";
import type { AppState, Lab, Meta } from "../types";
import { warningCount, type Readiness } from "../features/f09/types";
import { usePatientId } from "../session";
import { Skeleton } from "../components/ui";
import type { ProgressResponse } from "./Progress";

// Documents still waiting for a person to confirm what OCR read (same set as the dock badge).
const AWAITING_REVIEW = new Set(["needs_confirmation", "pending", "needs_manual_entry"]);

const VITALS: { key: string; label: string; unit: string }[] = [
  { key: "temperature_c", label: "Temp", unit: "°C" },
  { key: "heart_rate", label: "Pulse", unit: "/min" },
  { key: "bp", label: "BP", unit: "mmHg" },
  { key: "respiratory_rate", label: "Resp", unit: "/min" },
  { key: "spo2", label: "SpO₂", unit: "%" },
];

function when(value?: string | null) {
  if (!value) return "Time not recorded";
  return new Date(value).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function vitalValue(payload: Record<string, unknown>, key: string) {
  if (key === "bp") return payload.systolic != null && payload.diastolic != null ? `${payload.systolic}/${payload.diastolic}` : null;
  return payload[key] != null ? String(payload[key]) : null;
}

const flagged = (lab: Lab) => lab.flag === "low" || lab.flag === "high";

export function PatientOverviewPage() {
  const patientId = usePatientId();
  const state = useQuery<AppState>({
    queryKey: ["state", patientId],
    queryFn: () => get<AppState>(`/patients/${patientId}/state`),
    enabled: !!patientId,
  });
  const readiness = useQuery<Readiness>({ queryKey: ["discharge-readiness"], queryFn: () => get("/discharge/readiness") });
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta") });
  const progress = useQuery<ProgressResponse>({ queryKey: ["progress", patientId, null], queryFn: () => get(`/patients/${patientId}/progress`), enabled: !!patientId });
  const s = state.data;
  const egfr = s?.latest_labs.find((lab) => lab.name.toLowerCase() === "egfr");
  const stayDay = meta.data?.encounter.admitted_at && meta.data.demo_now
    ? Math.floor((Date.parse(meta.data.demo_now.slice(0, 10)) - Date.parse(meta.data.encounter.admitted_at.slice(0, 10))) / 86_400_000) + 1
    : null;

  const openAlerts = (s?.alerts ?? [])
    .filter((a) => a.status === "open")
    .sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "critical" ? -1 : 1));
  const criticalAlerts = openAlerts.filter((a) => a.severity === "critical").length;
  const openTasks = (s?.tasks ?? []).filter((t) => !["completed", "cancelled"].includes(t.status));
  const overdueTasks = openTasks.filter((t) => t.is_overdue);
  const unreviewedLabs = s?.unreviewed_labs ?? [];
  const awaitingDocs = (s?.documents ?? []).filter((d) => AWAITING_REVIEW.has(d.ocr_status));
  const notes = Object.values(s?.notes ?? {}).sort((a, b) => b.occurred_at.localeCompare(a.occurred_at));
  const readyItems = readiness.data?.items ?? [];
  const readyCount = readyItems.filter((i) => i.present).length;
  const medDiffs = readiness.data?.warnings.unresolved_medicine_differences.length ?? 0;
  const dischargeWarnings = warningCount(readiness.data?.warnings);
  const signed = readiness.data?.already_signed || s?.discharge_signed;

  const kpis = s ? [
    { key: "alerts", label: "Open alerts", value: String(openAlerts.length), note: `${criticalAlerts} critical`, to: "/safety?tab=alerts", tone: criticalAlerts ? "critical" : "" },
    { key: "overdue", label: "Overdue tasks", value: String(overdueTasks.length), note: `${openTasks.length} open tasks`, to: "/tasks", tone: overdueTasks.length ? "warning" : "" },
    { key: "labs", label: "Results to review", value: String(unreviewedLabs.length), note: `${s.latest_labs.length} latest results`, to: "/notes?tab=labs", tone: unreviewedLabs.length ? "critical" : "" },
    { key: "docs", label: "Reports to confirm", value: String(awaitingDocs.length), note: `${s.documents.length} document${s.documents.length === 1 ? "" : "s"} on file`, to: "/documents?tab=inbound", tone: "" },
    { key: "meds", label: "Medicine differences", value: String(medDiffs), note: "Home vs inpatient", to: "/safety?tab=meds", tone: medDiffs ? "warning" : "" },
    { key: "discharge", label: "Discharge documents", value: signed ? "Signed" : `${readyCount}/${readyItems.length}`, note: dischargeWarnings ? `${dischargeWarnings} warnings` : "Required items", to: "/discharge", tone: "" },
  ] : [];

  return (
    <div className="page his-dash">
      <header className="page-header">
        <div className="page-header-text">
          <h1 className="page-h1">Patient Dashboard</h1>
          <p className="page-desc">What needs attention for this patient, the latest results and what to do next.</p>
        </div>
        <div className="page-header-actions button-row">
          <Link className="btn btn-primary" to="/notes?tab=consult">Start consultation</Link>
          <Link className="btn" to="/timeline">Open chart</Link>
        </div>
      </header>

      {progress.data ? (
        <Link to="/progress" className="pr-strip">
          <b>OVERALL PROGRESS: {progress.data.overall.percent}%</b>
          <span>{progress.data.overall.done} of {progress.data.overall.total} checks done</span>
          <span>TODAY: {progress.data.daily.tasks_done}/{progress.data.daily.tasks_total} tasks completed, {progress.data.daily.notes_verified}/{progress.data.daily.notes_total} notes verified</span>
          <span className="pr-strip-go">View progress &rarr;</span>
        </Link>
      ) : null}


      {state.isError ? <p className="error-box" role="alert">The patient record could not be loaded. Try again in a moment.</p> : null}

      <div className="his-dash-cols">
        <section className="his-box">
          <h2 className="his-box-title">Patient summary</h2>
          {s ? (
            <table className="table">
              <thead><tr><th>Item</th><th className="right">Count</th><th>Note</th></tr></thead>
              <tbody>
                {kpis.map((k) => (
                  <tr key={k.key}>
                    <td><Link to={k.to}>{k.label}</Link></td>
                    <td className={`right strong ${k.tone ? `his-tone-${k.tone}` : ""}`}>{k.value}</td>
                    <td className="muted">{k.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Skeleton count={6} />}
        </section>

        <section className="his-box">
          <h2 className="his-box-title">Latest vitals {s?.vitals ? `(${when(s.vitals.occurred_at)})` : ""}</h2>
          {!s ? <Skeleton count={5} /> : s.vitals ? (
            <table className="table">
              <thead><tr><th>Vital</th><th className="right">Value</th><th>Unit</th></tr></thead>
              <tbody>
                {VITALS.map((v) => {
                  const value = vitalValue(s.vitals!.payload ?? {}, v.key);
                  return <tr key={v.key}><td>{v.label}</td><td className="right strong">{value ?? "-"}</td><td className="muted">{value ? v.unit : "Not documented"}</td></tr>;
                })}
              </tbody>
            </table>
          ) : <p className="his-box-empty">No vitals documented.</p>}
        </section>
      </div>

      <section className="his-box">
        <h2 className="his-box-title">Needs attention</h2>
        {!s ? <Skeleton variant="rows" count={3} /> : openAlerts.length + overdueTasks.length + unreviewedLabs.length === 0 ? (
          <p className="his-box-empty">Nothing needs attention right now.</p>
        ) : (
          <table className="table">
            <thead><tr><th>Type</th><th>Item</th><th>Detail</th><th /></tr></thead>
            <tbody>
              {openAlerts.map((a) => (
                <tr key={a.id}>
                  <td className={`strong his-tone-${a.severity === "critical" ? "critical" : "warning"}`}>{a.severity === "critical" ? "Critical" : "Alert"}</td>
                  <td>{a.title}</td><td className="muted">{a.recommended_action}</td>
                  <td className="right"><Link className="btn btn-sm" to="/safety?tab=alerts">Review</Link></td>
                </tr>
              ))}
              {overdueTasks.map((t) => (
                <tr key={t.id}>
                  <td className="strong his-tone-warning">Overdue</td>
                  <td>{t.title}</td><td className="muted">{t.owner || t.assigned_to || "Unassigned"} · due {when(t.due_at)}</td>
                  <td className="right"><Link className="btn btn-sm" to="/tasks">Open</Link></td>
                </tr>
              ))}
              {unreviewedLabs.map((l) => (
                <tr key={l.event_id}>
                  <td className="strong his-tone-info">Unreviewed</td>
                  <td>{l.name} {l.value} {l.unit}</td><td className="muted">Reference {l.reference_range || "not documented"} · {when(l.collected_at)}</td>
                  <td className="right"><Link className="btn btn-sm" to="/notes?tab=labs">Review</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <div className="his-dash-cols">
        <section className="his-box">
          <h2 className="his-box-title">Latest lab results</h2>
          {!s ? <Skeleton variant="rows" count={4} /> : s.latest_labs.length ? (
            <table className="table">
              <thead><tr><th>Test</th><th className="right">Result</th><th>Unit</th><th>Reference</th><th>Flag</th></tr></thead>
              <tbody>
                {s.latest_labs.map((lab) => (
                  <tr key={lab.event_id}>
                    <td>{lab.name}</td>
                    <td className={`right strong ${flagged(lab) ? "his-tone-critical" : ""}`}>{lab.value}</td>
                    <td className="muted">{lab.unit}</td>
                    <td className="muted">{lab.reference_range || "-"}</td>
                    <td className={flagged(lab) ? "his-tone-critical strong" : "muted"}>{lab.flag ? lab.flag.toUpperCase() : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="his-box-empty">No lab results yet.</p>}
        </section>

        <section className="his-box">
          <h2 className="his-box-title">Current medicines</h2>
          {!s ? <Skeleton variant="rows" count={4} /> : s.active_meds.length ? (
            <table className="table">
              <thead><tr><th>Drug</th><th>Dose</th><th>Route</th><th>Frequency</th></tr></thead>
              <tbody>
                {s.active_meds.map((m) => (
                  <tr key={m.event_id}><td>{m.drug}</td><td>{m.dose || "-"}</td><td>{m.route || "-"}</td><td>{m.frequency || "-"}</td></tr>
                ))}
              </tbody>
            </table>
          ) : <p className="his-box-empty">No active medicine orders.</p>}
        </section>
      </div>

      <section className="his-box">
        <h2 className="his-box-title">Recent notes</h2>
        {!s ? <Skeleton variant="rows" count={3} /> : notes.length ? (
          <table className="table">
            <thead><tr><th>Note</th><th>Recorded</th><th /></tr></thead>
            <tbody>
              {notes.slice(0, 8).map((n) => (
                <tr key={n.event_id}><td>{n.title}</td><td className="muted">{when(n.occurred_at)}</td><td className="right"><Link className="btn btn-sm" to="/timeline">Open chart</Link></td></tr>
              ))}
            </tbody>
          </table>
        ) : <p className="his-box-empty">No signed notes yet.</p>}
      </section>
    </div>
  );
}
