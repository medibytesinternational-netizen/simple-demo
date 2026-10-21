import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "../api";
import type { HospitalDashboard } from "../types";

function fmt(value: number) {
  return Number(value || 0).toLocaleString();
}

function actionBadge(action: string) {
  if (action.includes("approved") || action.includes("committed")) return "badge-success";
  if (action.includes("created") || action.includes("prepared") || action.includes("assigned")) return "badge-ai";
  if (action.includes("dismissed") || action.includes("rejected") || action.includes("escalated")) return "badge-critical";
  return "badge-neutral";
}

export function DashboardPage() {
  const dashboard = useQuery<HospitalDashboard>({
    queryKey: ["hospital-dashboard"],
    queryFn: () => get("/hospital/dashboard"),
  });
  const data = dashboard.data;
  const summary = data?.summary;
  const wardEntries = Object.entries(summary?.wards || {});

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Hospital command centre</h1>
          <div className="page-sub">
            F14 is a hospital-scoped queue, not a single-encounter scorecard. Counts come from the live demo database and the demo clock; value KPIs remain illustrative.
          </div>
        </div>
        <div className="page-actions">
          <span className="badge badge-ai">{data?.hospital.name || "hospital scope"}</span>
          <span className="badge badge-warning">value KPIs illustrative</span>
        </div>
      </div>

      <div className="grid-4 mb-3">
        <div className="card stat">
          <div className="stat-label">Active encounters</div>
          <div className="stat-value">{fmt(summary?.active_encounters ?? 0)}</div>
          <div className="stat-note">{fmt(summary?.patients ?? 0)} patients in the seeded cohort</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Drafts awaiting review</div>
          <div className="stat-value">{fmt(summary?.pending_drafts ?? 0)}</div>
          <div className="stat-note">{fmt(summary?.discharge_reviews ?? 0)} discharge drafts</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Open alerts</div>
          <div className="stat-value" style={{ color: summary?.critical_alerts ? "var(--critical)" : "var(--success)" }}>{fmt(summary?.open_alerts ?? 0)}</div>
          <div className="stat-note">{fmt(summary?.critical_alerts ?? 0)} critical; every dismissal needs a reason</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Tasks overdue</div>
          <div className="stat-value" style={{ color: summary?.overdue_tasks ? "var(--warning)" : undefined }}>{fmt(summary?.overdue_tasks ?? 0)}</div>
          <div className="stat-note">{fmt(summary?.escalated_tasks ?? 0)} escalated with a reason</div>
        </div>
      </div>

      <div className="grid-4 mb-3">
        <div className="card stat">
          <div className="stat-label">Documents pending</div>
          <div className="stat-value">{fmt(summary?.pending_documents ?? 0)}</div>
          <div className="stat-note">OCR needs human confirmation</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Open referrals</div>
          <div className="stat-value">{fmt(summary?.open_referrals ?? 0)}</div>
          <div className="stat-note">Sent or acknowledged, not yet completed</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Investigation requests</div>
          <div className="stat-value">{fmt(summary?.pending_investigations ?? 0)}</div>
          <div className="stat-note">Approved, not yet marked exported</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Claim gaps</div>
          <div className="stat-value">{fmt(summary?.claim_gaps ?? 0)}</div>
          <div className="stat-note">Missing docs, underbilled, unsupported, contradictions</div>
        </div>
      </div>

      <div className="split-main">
        <div className="flex-col gap-3">
          <div className="card">
            <div className="card-head">
              <div><div className="card-title">Hospital queue</div><div className="card-sub">Every row is a real encounter or task record. No aggregate is hand-typed.</div></div>
              <span className="badge badge-neutral">{data?.patients.length || 0} patients</span>
            </div>
            <table className="table">
              <thead><tr><th>Patient</th><th>Location</th><th>Open work</th><th>Flags</th><th className="right">Open</th></tr></thead>
              <tbody>
                {data?.patients.map((patient) => (
                  <tr key={patient.patient_id}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{patient.name}</div>
                      <div className="small muted">{patient.mrn} · {patient.age}{patient.sex.slice(0, 1)} · {patient.encounter_status}</div>
                    </td>
                    <td className="small">
                      {patient.ward || "—"}<div className="small muted">{patient.bed || ""} {patient.kind || ""}</div>
                    </td>
                    <td className="small">
                      <div>{patient.pending_drafts} drafts · {patient.overdue_tasks} overdue</div>
                      <div className="small muted">{patient.open_alerts} alerts · {patient.open_referrals} referrals</div>
                    </td>
                    <td>
                      <div className="pill-row">
                        {patient.flags.map((flag) => (
                          <span className={`badge ${flag.includes("critical") || flag.includes("escalated") ? "badge-critical" : "badge-warning"}`} key={flag}>{flag}</span>
                        ))}
                        {!patient.flags.length ? <span className="badge badge-success">clear</span> : null}
                      </div>
                    </td>
                    <td className="right">
                      {patient.patient_id === "pat_ravi" ? <Link className="btn btn-sm" to="/notes">Open record</Link> : <span className="small muted">queue row</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card">
            <div className="card-head">
              <div><div className="card-title">Recent audit — hospital scope</div><div className="card-sub">Who did what, with model and evidence metadata where applicable</div></div>
              <span className="badge badge-neutral">last 12</span>
            </div>
            <div className="list">
              {data?.recent_audit.map((entry) => (
                <div className="list-row" key={entry.id} style={{ display: "block" }}>
                  <div className="flex items-center justify-between gap-2">
                    <span className={`badge ${actionBadge(entry.action)}`}>{entry.action.replaceAll("_", " ")}</span>
                    <span className="mono small muted">{new Date(entry.created_at).toLocaleString()}</span>
                  </div>
                  <div className="fs-13 mt-1">
                    <strong>{entry.actor_name}</strong>
                    <span className="muted"> · {entry.entity_type}</span>
                    <span className="mono small muted"> {entry.entity_id}</span>
                  </div>
                  {entry.meta?.model || entry.meta?.mode ? (
                    <div className="small muted mt-1">model {entry.meta.model || "cached"} · mode {entry.meta.mode || "cached"}</div>
                  ) : null}
                </div>
              ))}
              {!data?.recent_audit.length ? <div className="empty">No audit entries.</div> : null}
            </div>
          </div>
        </div>

        <div className="flex-col gap-3">
          <div className="card">
            <div className="card-head"><div className="card-title">Ward load</div><span className="badge badge-neutral">active encounters</span></div>
            <div className="card-pad">
              {wardEntries.map(([ward, count]) => (
                <div className="check-row" key={ward}>
                  <span className="muted" style={{ flex: 1 }}>{ward}</span>
                  <span className="mono fs-20">{count}</span>
                </div>
              ))}
              {!wardEntries.length ? <div className="small muted">No active ward beds.</div> : null}
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <div><div className="card-title">Primary-patient claim posture</div><div className="card-sub">Review readiness, not a prediction</div></div>
              <span className={`badge ${data?.claim.status === "review_ready" ? "badge-success" : "badge-warning"}`}>
                {data?.claim.status?.replaceAll("_", " ") || "—"}
              </span>
            </div>
            <div className="card-pad">
              <div className="flex items-center justify-between">
                <span className="muted fs-13">Seeded bill total</span>
                <span className="mono fs-20">INR {fmt(data?.claim.total_amount ?? 0)}</span>
              </div>
              <div className="check-row">
                <span className="muted fs-13" style={{ flex: 1 }}>Expected total</span>
                <span className="mono">INR {fmt(data?.claim.expected_total_amount ?? 0)}</span>
              </div>
              <div className="check-row">
                <span className="muted fs-13" style={{ flex: 1 }}>Underbilled</span>
                <span className={`badge ${data?.claim.underbilled_items.length ? "badge-warning" : "badge-success"}`}>
                  {data?.claim.underbilled_items.length || 0} items · INR {fmt(data?.claim.underbilled_amount ?? 0)}
                </span>
              </div>
              <div className="check-row">
                <span className="muted fs-13" style={{ flex: 1 }}>Contradictions</span>
                <span className={`badge ${data?.claim.contradictions.length ? "badge-critical" : "badge-success"}`}>
                  {data?.claim.contradictions.length || 0} open
                </span>
              </div>
              <div className="section-label" style={{ marginTop: 14 }}>Missing before review</div>
              {data?.claim.missing_documents.length ? (
                <div className="pill-row">
                  {data.claim.missing_documents.map((item) => <span className="badge badge-critical" key={item}>{item}</span>)}
                </div>
              ) : (
                <span className="badge badge-success">Nothing missing</span>
              )}
              <div className="button-row mt-4">
                <Link className="btn btn-sm" to="/revenue">Open claim pack</Link>
                <Link className="btn btn-sm" to="/documents?tab=followup">Follow-up request</Link>
                <Link className="btn btn-sm" to="/discharge">Open discharge</Link>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <div><div className="card-title">Value snapshot</div><div className="card-sub">Illustrative, not measured outcomes</div></div>
              <span className="badge badge-warning">illustrative</span>
            </div>
            <div className="card-pad">
              <div className="check-row">
                <span className="muted" style={{ flex: 1 }}>Clinician minutes saved</span>
                <span className="mono fs-20">{fmt(data?.illustrative.clinician_minutes_saved ?? 0)}</span>
              </div>
              <div className="check-row">
                <span className="muted" style={{ flex: 1 }}>Billed value at risk</span>
                <span className="mono fs-20">INR {fmt(data?.illustrative.revenue_at_risk ?? 0)}</span>
              </div>
              <div className="check-row">
                <span className="muted" style={{ flex: 1 }}>Leakage findings</span>
                <span className="mono fs-20">{fmt(data?.illustrative.leakage_identified ?? 0)}</span>
              </div>
              <div className="banner warning mt-3">{data?.illustrative.note || "Illustrative KPIs only."}</div>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><div className="card-title">Honesty panel</div><span className="badge badge-neutral">say this unprompted</span></div>
            <div className="card-pad">
              <div className="section-label">Working for real</div>
              <div className="small" style={{ lineHeight: 1.7 }}>
                Navigation, timeline, rule engine, tasks, assignment, acknowledgement, escalation, drafts, review and approve, audit, every model call, OCR confirmation, referral status, claim checklist.
              </div>
              <div className="section-label">Seeded / faked</div>
              <div className="small" style={{ lineHeight: 1.7 }}>
                Cohort patients, device feeds, insurer submission, billing data, value KPIs. “Send” and “export” are audited demo status changes; they do not transmit. The bill is seeded.
              </div>
              <div className="banner mt-3" style={{ lineHeight: 1.6 }}>
                “The interesting part is not the generation. It is the boundary: rules decide, the model phrases, and only a human writes.”
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><div className="card-title">Demo shortcuts</div></div>
            <div className="card-pad button-row">
              <Link className="btn btn-sm" to="/notes?tab=consult">F1 consult</Link>
              <Link className="btn btn-sm" to="/notes?tab=icu">F7 ICU</Link>
              <Link className="btn btn-sm" to="/notes?tab=referral">F11 referral</Link>
              <Link className="btn btn-sm" to="/documents?tab=requisition">F10 requisition</Link>
              <Link className="btn btn-sm" to="/tasks">F15 tasks</Link>
              <Link className="btn btn-sm" to="/revenue">F12 claim</Link>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
