import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "../api";
import type { AppState, Lab, Meta } from "../types";
import { warningCount, type Readiness } from "../features/f09/types";
import { usePatientId } from "../session";
import { HalfGauge, PillBars, parseRange } from "../components/charts";
import { Icon } from "../components/icons";
import { PatientStrip } from "../components/PatientStrip";
import { EmptyState, Skeleton } from "../components/ui";

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

/** Bar height = result against its reference limit, with the limit drawn at half height. */
function labShare(lab: Lab) {
  const value = Number(lab.value);
  const range = parseRange(lab.reference_range);
  const limit = range?.high ?? range?.low;
  if (!Number.isFinite(value) || !limit) return null;
  return value / (2 * limit);
}

export function PatientOverviewPage() {
  const patientId = usePatientId();
  const state = useQuery<AppState>({
    queryKey: ["state", patientId],
    queryFn: () => get<AppState>(`/patients/${patientId}/state`),
    enabled: !!patientId,
  });
  const readiness = useQuery<Readiness>({ queryKey: ["discharge-readiness"], queryFn: () => get("/discharge/readiness") });
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta") });
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

  const charted = (s?.latest_labs ?? []).map((lab) => ({ lab, share: labShare(lab) })).filter((x) => x.share !== null);
  const worst = [...charted].sort((a, b) => Math.abs((b.share ?? 0) - 0.5) - Math.abs((a.share ?? 0) - 0.5))[0];

  const kpis = s ? [
    { key: "alerts", label: "Open alerts", value: openAlerts.length, note: `${criticalAlerts} critical`, to: "/safety?tab=alerts", feature: true },
    { key: "overdue", label: "Overdue tasks", value: overdueTasks.length, note: `${openTasks.length} open tasks`, to: "/tasks", tone: overdueTasks.length ? "warning" : "" },
    { key: "labs", label: "Results to review", value: unreviewedLabs.length, note: `${s.latest_labs.length} latest results`, to: "/notes?tab=labs", tone: unreviewedLabs.length ? "critical" : "" },
    { key: "docs", label: "Reports to confirm", value: awaitingDocs.length, note: `${s.documents.length} document${s.documents.length === 1 ? "" : "s"} on file`, to: "/documents?tab=inbound" },
  ] : [];

  // The single most important next step: top alert, else overdue task, else a result to review.
  const topAlert = openAlerts[0];
  const topTask = overdueTasks[0];
  const nextStep = topAlert
    ? { title: topAlert.title, meta: topAlert.severity === "critical" ? "Critical alert" : "Alert", detail: topAlert.recommended_action, label: "Review alert", icon: "safety", to: "/safety?tab=alerts" }
    : topTask
      ? { title: topTask.title, meta: `Overdue · due ${when(topTask.due_at)}`, detail: topTask.owner || topTask.assigned_to || "Unassigned", label: "Open tasks", icon: "tasks", to: "/tasks" }
      : unreviewedLabs[0]
        ? { title: `${unreviewedLabs[0].name} ${unreviewedLabs[0].value} ${unreviewedLabs[0].unit}`, meta: "Unreviewed result", detail: `Reference ${unreviewedLabs[0].reference_range || "not documented"}`, label: "Review result", icon: "lab", to: "/notes?tab=labs" }
        : null;

  return (
    <div className="page dk-page pg-patient-overview">
      <header className="dk-head">
        <div>
          <h1 className="dk-title">Patient dashboard</h1>
          <p className="dk-sub">What needs attention for this patient, the latest results and what to do next.</p>
        </div>
        <div className="dk-actions">
          <Link className="dk-btn dk-btn-primary" to="/notes?tab=consult"><Icon name="consult" size={16} /> Start consultation</Link>
          <Link className="dk-btn dk-btn-outline" to="/timeline"><Icon name="chart" size={16} /> Open chart</Link>
        </div>
      </header>

      <PatientStrip meta={meta.data} openAlerts={openAlerts.length} egfr={egfr} stayDay={stayDay} />

      {state.isError ? <EmptyState icon="alert" title="The patient record could not be loaded">Try again in a moment.</EmptyState> : null}

      <section className="dk-kpis" aria-label="Patient at a glance">
        {s ? kpis.map((kpi) => (
          <Link key={kpi.key} to={kpi.to} className={`dk-kpi ${kpi.feature ? "is-feature" : ""} ${kpi.tone ? `tone-${kpi.tone}` : ""}`} aria-label={`${kpi.label}: ${kpi.value}. ${kpi.note}.`}>
            <span className="dk-kpi-label">{kpi.label}</span>
            <span className="dk-kpi-arrow" aria-hidden="true"><Icon name="arrow" size={15} /></span>
            <span className="dk-kpi-value">{kpi.value}</span>
            <span className="dk-kpi-note">{kpi.note}</span>
          </Link>
        )) : Array.from({ length: 4 }, (_, i) => <div className="dk-kpi" key={i} aria-busy="true"><Skeleton count={3} /></div>)}
      </section>

      <div className="dk-grid">
        <section className="dk-card span-5" aria-labelledby="po-labs">
          <div className="dk-card-head">
            <div>
              <h2 className="dk-card-title" id="po-labs">Lab results</h2>
              <p className="dk-card-sub">Latest value of each test against its reference limit</p>
            </div>
            <Link className="dk-btn dk-btn-outline dk-btn-sm" to="/notes?tab=labs">All results</Link>
          </div>
          {!s ? <Skeleton count={4} /> : charted.length ? (
            <PillBars
              ariaLabel="Latest lab results against reference limits"
              markerAt={0.5}
              markerLabel="Reference limit"
              highlight={worst?.lab.event_id}
              items={charted.map(({ lab, share }) => ({
                key: lab.event_id, label: lab.name, valueText: `${lab.value}`, share: share!,
                tone: flagged(lab) ? "critical" : "accent",
                detail: `${lab.unit}, reference ${lab.reference_range}${lab.flag ? `, ${lab.flag}` : ""}`,
              }))}
            />
          ) : <EmptyState icon="lab" title="No lab results with a reference range yet" />}
          <p className="dk-card-foot">Dashed line: reference limit. Red: outside the reference range. Values are exact; units are in the results table.</p>
        </section>

        <section className="dk-card dk-reminder span-3" aria-labelledby="po-next">
          <div className="dk-card-head"><h2 className="dk-card-title" id="po-next">Next step</h2></div>
          {!s ? <Skeleton count={3} /> : nextStep ? (
            <>
              <div className="dk-reminder-body">
                <p className="dk-reminder-title">{nextStep.title}</p>
                <div className="dk-reminder-meta">{nextStep.meta}</div>
                <p className="dk-reminder-detail">{nextStep.detail}</p>
              </div>
              <Link className="dk-btn dk-btn-primary" to={nextStep.to}><Icon name={nextStep.icon} size={16} /> {nextStep.label}</Link>
            </>
          ) : <EmptyState icon="check" title="Nothing urgent right now" />}
        </section>

        <section className="dk-card span-4" aria-labelledby="po-meds">
          <div className="dk-card-head">
            <h2 className="dk-card-title" id="po-meds">Current medicines</h2>
            <Link className="dk-btn dk-btn-outline dk-btn-sm" to="/safety?tab=meds">Reconcile</Link>
          </div>
          {medDiffs ? <Link to="/safety?tab=meds" className="dk-callout"><Icon name="pill" size={15} /> {medDiffs} unresolved difference{medDiffs === 1 ? "" : "s"} with home medicines</Link> : null}
          {!s ? <Skeleton variant="rows" count={4} /> : s.active_meds.length ? (
            <ul className="dk-list">
              {s.active_meds.slice(0, 5).map((m) => (
                <li key={m.event_id} className="dk-item">
                  <span className="dk-item-icon tone-info" aria-hidden="true"><Icon name="pill" size={15} /></span>
                  <span className="dk-item-text">
                    <span className="dk-item-title">{m.drug}</span>
                    <span className="dk-item-meta">{[m.dose, m.route, m.frequency].filter(Boolean).join(" · ")}</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : <EmptyState icon="pill" title="No active medicine orders" />}
        </section>

        <section className="dk-card span-5" aria-labelledby="po-attention">
          <div className="dk-card-head">
            <div>
              <h2 className="dk-card-title" id="po-attention">Needs attention</h2>
              <p className="dk-card-sub">Open alerts, overdue tasks and unreviewed results</p>
            </div>
          </div>
          {!s ? <Skeleton variant="rows" count={4} /> : openAlerts.length + overdueTasks.length + unreviewedLabs.length === 0 ? (
            <EmptyState icon="check" title="Nothing needs attention right now" />
          ) : (
            <ul className="dk-list po-scroll">
              {openAlerts.map((a) => (
                <li key={a.id}><Link to="/safety?tab=alerts" className="dk-item">
                  <span className={`dk-item-icon tone-${a.severity}`} aria-hidden="true"><Icon name="safety" size={15} /></span>
                  <span className="dk-item-text"><span className="dk-item-title">{a.title}</span><span className="dk-item-meta">{a.recommended_action}</span></span>
                  <span className={`dk-tag tone-${a.severity}`}>{a.severity === "critical" ? "Critical" : "Alert"}</span>
                </Link></li>
              ))}
              {overdueTasks.map((t) => (
                <li key={t.id}><Link to="/tasks" className="dk-item">
                  <span className="dk-item-icon tone-warning" aria-hidden="true"><Icon name="tasks" size={15} /></span>
                  <span className="dk-item-text"><span className="dk-item-title">{t.title}</span><span className="dk-item-meta">{t.owner || t.assigned_to || "Unassigned"} · due {when(t.due_at)}</span></span>
                  <span className="dk-tag tone-warning">Overdue</span>
                </Link></li>
              ))}
              {unreviewedLabs.map((l) => (
                <li key={l.event_id}><Link to="/notes?tab=labs" className="dk-item">
                  <span className="dk-item-icon tone-info" aria-hidden="true"><Icon name="lab" size={15} /></span>
                  <span className="dk-item-text"><span className="dk-item-title">{l.name} {l.value} {l.unit}</span><span className="dk-item-meta">Reference {l.reference_range || "not documented"} · {when(l.collected_at)}</span></span>
                  <span className="dk-tag tone-info">Unreviewed</span>
                </Link></li>
              ))}
            </ul>
          )}
        </section>

        <section className="dk-card span-4" aria-labelledby="po-discharge">
          <div className="dk-card-head">
            <h2 className="dk-card-title" id="po-discharge">Discharge readiness</h2>
            <Link className="dk-btn dk-btn-outline dk-btn-sm" to="/discharge">Open</Link>
          </div>
          {readiness.isLoading ? <Skeleton count={4} /> : readiness.isError ? (
            <EmptyState icon="discharge" title="Readiness could not be checked" />
          ) : signed ? (
            <EmptyState icon="check" title="Discharge summary signed" />
          ) : (
            <>
              <HalfGauge
                value={readyCount} max={readyItems.length} label="Required discharge documentation"
                caption={`${readyCount} of ${readyItems.length} required items documented`}
                segments={[
                  { key: "done", label: "Documented", value: readyCount, tone: "fill" },
                  { key: "missing", label: "Missing", value: readyItems.length - readyCount, tone: "hatch" },
                  { key: "warn", label: "Warnings", value: dischargeWarnings, tone: "deep" },
                ]}
              />
              {dischargeWarnings ? <p className="dk-card-foot">{dischargeWarnings} warning{dischargeWarnings === 1 ? "" : "s"} need a written reason before signing.</p> : null}
            </>
          )}
        </section>

        <section className="dk-card dk-dark span-3" aria-labelledby="po-vitals">
          <div className="dk-card-head">
            <div>
              <h2 className="dk-card-title" id="po-vitals">Latest vitals</h2>
              <p className="dk-card-sub">{s?.vitals ? `Recorded ${when(s.vitals.occurred_at)}` : "No vitals documented"}</p>
            </div>
          </div>
          {!s ? <Skeleton count={3} /> : s.vitals ? (
            <dl className="po-vitals-dark">
              {VITALS.map((v) => {
                const value = vitalValue(s.vitals!.payload ?? {}, v.key);
                return (
                  <div key={v.key}>
                    <dt>{v.label}</dt>
                    <dd>{value ?? "Not documented"}{value ? <small>{v.unit}</small> : null}</dd>
                  </div>
                );
              })}
            </dl>
          ) : null}
        </section>

        <section className="dk-card span-7" aria-labelledby="po-notes">
          <div className="dk-card-head">
            <h2 className="dk-card-title" id="po-notes">Recent notes</h2>
            <Link className="dk-btn dk-btn-outline dk-btn-sm" to="/timeline">Full chart</Link>
          </div>
          {!s ? <Skeleton variant="rows" count={3} /> : notes.length ? (
            <ul className="dk-list">
              {notes.slice(0, 5).map((n) => (
                <li key={n.event_id}><Link to="/timeline" className="dk-item">
                  <span className="dk-item-icon" aria-hidden="true"><Icon name="progress" size={15} /></span>
                  <span className="dk-item-text"><span className="dk-item-title">{n.title}</span><span className="dk-item-meta">{when(n.occurred_at)}</span></span>
                  <Icon name="chevron" size={15} />
                </Link></li>
              ))}
            </ul>
          ) : <EmptyState icon="progress" title="No signed notes yet" />}
        </section>

        <section className="dk-card span-5" aria-labelledby="po-work">
          <div className="dk-card-head"><h2 className="dk-card-title" id="po-work">Work for this patient</h2></div>
          {!s ? <Skeleton count={3} /> : (
            <div className="dk-stats">
              <Link to="/tasks" className="dk-stat"><span className="dk-stat-value">{openTasks.length}</span><span className="dk-stat-label">Open tasks</span></Link>
              <Link to="/tasks" className={`dk-stat ${overdueTasks.length ? "tone-warning" : ""}`}><span className="dk-stat-value">{overdueTasks.length}</span><span className="dk-stat-label">Overdue</span></Link>
              <Link to="/documents?tab=inbound" className={`dk-stat ${awaitingDocs.length ? "tone-info" : ""}`}><span className="dk-stat-value">{awaitingDocs.length}</span><span className="dk-stat-label">Reports to confirm</span></Link>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
