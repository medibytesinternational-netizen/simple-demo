import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ALERT_TARGET } from "../components/nextStep";
import { get } from "../api";
import type { AppState, Lab, Meta } from "../types";
import { warningCount, type Readiness } from "../features/f09/types";
import { usePatientId } from "../session";
import { Disclosure, Skeleton } from "../components/ui";
import { canSee, currentRole } from "../components/roles";
import type { ProgressResponse } from "./Progress";

// Patient Dashboard, laid out by MoSCoW so a nurse or doctor new to the patient sees the whole picture fast:
// Must  = identity, allergies, problems, needs attention, vitals, care so far (every input given)
// Should = medicines, abnormal labs, status counts
// Could = full tables and notes, collapsed

// Documents still waiting for a person to confirm what OCR read (same set as the dock badge).
const AWAITING_REVIEW = new Set(["needs_confirmation", "pending", "needs_manual_entry"]);
const LIVE = { refetchInterval: 30_000, refetchOnWindowFocus: true } as const;
const ATTENTION_LIMIT = 5;
const MEDS_LIMIT = 6;

const VITALS: { key: string; label: string; unit: string }[] = [
  { key: "temperature_c", label: "Temp", unit: "°C" },
  { key: "heart_rate", label: "Pulse", unit: "/min" },
  { key: "bp", label: "BP", unit: "mmHg" },
  { key: "respiratory_rate", label: "Resp", unit: "/min" },
  { key: "spo2", label: "SpO₂", unit: "%" },
];

type Referral = { id: string; specialty: string; question: string; urgency: string; status: string; created_at: string };

function when(value?: string | null) {
  if (!value) return "Time not recorded";
  return new Date(value).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function vitalValue(payload: Record<string, unknown>, key: string) {
  if (key === "bp") return payload.systolic != null && payload.diastolic != null ? `${payload.systolic}/${payload.diastolic}` : null;
  return payload[key] != null ? String(payload[key]) : null;
}

const flagged = (lab: Lab) => lab.flag === "low" || lab.flag === "high";

// A note field may be a string, a claim {text}, or a list of either. Return the first readable line.
function gist(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map((v) => gist(v).replace(/[.;\s]+$/, "")).filter(Boolean).slice(0, 2).join("; ");
  if (typeof value === "object" && "text" in (value as object)) return String((value as { text: unknown }).text ?? "");
  return "";
}

function firstGist(payload: Record<string, unknown> | undefined, keys: string[]) {
  for (const key of keys) {
    const text = gist(payload?.[key]);
    if (text && text.toLowerCase() !== "none") return text;
  }
  return "";
}

const clip = (text: string, max = 110) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

export function PatientOverviewPage() {
  const patientId = usePatientId();
  const state = useQuery<AppState>({
    queryKey: ["state", patientId],
    queryFn: () => get<AppState>(`/patients/${patientId}/state`),
    enabled: !!patientId,
    ...LIVE,
  });
  const readiness = useQuery<Readiness>({ queryKey: ["discharge-readiness"], queryFn: () => get("/discharge/readiness"), ...LIVE });
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta") });
  const progress = useQuery<ProgressResponse>({ queryKey: ["progress", patientId, null], queryFn: () => get(`/patients/${patientId}/progress`), enabled: !!patientId, ...LIVE });
  const referrals = useQuery({ queryKey: ["referrals"], queryFn: () => get<{ referrals: Referral[] }>("/referrals"), ...LIVE });

  const s = state.data;
  const p = s?.patient;
  const enc = s?.encounter;
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
  const abnormalLabs = (s?.latest_labs ?? []).filter(flagged);
  const awaitingDocs = (s?.documents ?? []).filter((d) => AWAITING_REVIEW.has(d.ocr_status));
  const notes = Object.values(s?.notes ?? {}).sort((a, b) => b.occurred_at.localeCompare(a.occurred_at));
  const readyItems = readiness.data?.items ?? [];
  const readyCount = readyItems.filter((i) => i.present).length;
  const medDiffs = readiness.data?.warnings.unresolved_medicine_differences.length ?? 0;
  const dischargeWarnings = warningCount(readiness.data?.warnings);
  const signed = readiness.data?.already_signed || s?.discharge_signed;
  const latestReferral = referrals.data?.referrals[0];

  // Needs attention: one list, critical first, capped so the top band stays short.
  const attention = [
    ...openAlerts.map((a) => ({
      key: a.id, tone: a.severity === "critical" ? "critical" : "warning", type: a.severity === "critical" ? "Critical" : "Alert",
      item: a.title, detail: a.recommended_action, to: ALERT_TARGET[a.rule_id]?.to ?? "/safety?tab=alerts", action: ALERT_TARGET[a.rule_id]?.label ?? "Review",
    })),
    ...overdueTasks.map((t) => ({
      key: t.id, tone: "warning", type: "Overdue", item: t.title,
      detail: `${t.owner || t.assigned_to || "Unassigned"} · due ${when(t.due_at)}`, to: "/tasks", action: "Open",
    })),
    ...unreviewedLabs.map((l) => ({
      key: l.event_id, tone: "info", type: "Unreviewed", item: `${l.name} ${l.value} ${l.unit}`,
      detail: `Reference ${l.reference_range || "not documented"} · ${when(l.collected_at)}`, to: "/notes?tab=labs", action: "Review",
    })),
  ];

  // Care so far: the latest entry from every input given for this patient.
  const n = s?.notes ?? {};
  const care = s ? [
    { key: "opd", label: "OPD consultation", at: n.consult_note?.occurred_at, to: "/notes?tab=consult",
      text: firstGist(n.consult_note?.payload, ["chief_complaints", "history_of_present_illness"]) },
    { key: "admission", label: "Admission", at: n.admission_note?.occurred_at, to: "/timeline",
      text: [firstGist(n.admission_note?.payload, ["chief_complaint"]), firstGist(n.admission_note?.payload, ["plan"])].filter(Boolean).join(" — Plan: ") },
    { key: "round", label: "Ward round", at: n.round_note?.occurred_at, to: "/tasks",
      text: firstGist(n.round_note?.payload, ["note_claims", "proposed_tasks"]) },
    { key: "progress", label: "Progress note", at: n.progress_note?.occurred_at, to: "/progress",
      text: firstGist(n.progress_note?.payload, ["notes", "assessment", "plan"]) },
    { key: "nursing", label: "Nursing summary", at: n.nursing_summary?.occurred_at, to: "/timeline",
      text: firstGist(n.nursing_summary?.payload, ["summary", "notes", "note_claims"]) },
    { key: "referral", label: "Referral", at: latestReferral?.created_at, to: "/notes?tab=referral",
      text: latestReferral ? `${latestReferral.specialty} (${latestReferral.urgency}, ${latestReferral.status}) — ${latestReferral.question}` : "" },
    { key: "docs", label: "Documents", at: s.documents[0]?.uploaded_at, to: "/documents?tab=inbound",
      text: s.documents.length ? `${s.documents.length} on file${awaitingDocs.length ? `, ${awaitingDocs.length} to confirm` : ""} — latest ${s.documents[0].filename}` : "" },
    { key: "discharge", label: "Discharge", at: null, to: "/discharge",
      text: signed ? "Discharge summary signed" : readyItems.length ? `${readyCount}/${readyItems.length} items ready${dischargeWarnings ? `, ${dischargeWarnings} warnings` : ""}` : "" },
  ] : [];

  const kpis = s ? [
    { key: "alerts", label: "Open alerts", value: String(openAlerts.length), note: `${criticalAlerts} critical`, to: "/safety?tab=alerts", tone: criticalAlerts ? "critical" : "" },
    { key: "tasks", label: "Open tasks", value: String(openTasks.length), note: `${overdueTasks.length} overdue`, to: "/tasks", tone: overdueTasks.length ? "warning" : "" },
    { key: "labs", label: "Results to review", value: String(unreviewedLabs.length), note: `${s.latest_labs.length} latest`, to: "/notes?tab=labs", tone: unreviewedLabs.length ? "critical" : "" },
    { key: "docs", label: "Reports to confirm", value: String(awaitingDocs.length), note: `${s.documents.length} on file`, to: "/documents?tab=inbound", tone: "" },
    { key: "meds", label: "Medicine differences", value: String(medDiffs), note: "Home vs inpatient", to: "/safety?tab=meds", tone: medDiffs ? "warning" : "" },
    { key: "discharge", label: "Discharge", value: signed ? "Signed" : `${readyCount}/${readyItems.length}`, note: dischargeWarnings ? `${dischargeWarnings} warnings` : "Required items", to: "/discharge", tone: "" },
  ] : [];

  return (
    <div className="page his-dash">
      <header className="page-header">
        <div className="page-header-text">
          <h1 className="page-h1">Patient Dashboard</h1>
          <p className="page-desc">Everything about this patient at a glance. Updates as notes, results and orders are added.</p>
        </div>
        <div className="page-header-actions button-row">
          {canSee(currentRole(), "consult") ? <Link className="btn btn-primary" to="/notes?tab=consult">Start consultation</Link> : null}
          <Link className="btn" to="/timeline">Open chart</Link>
        </div>
      </header>

      {state.isError ? <p className="error-box" role="alert">The patient record could not be loaded. Try again in a moment.</p> : null}

      {/* MUST: who the patient is */}
      <section className="pt-banner" aria-label="Patient identity">
        {!p || !enc ? <Skeleton count={2} /> : (
          <>
            <div className="pt-banner-id">
              <span className="pt-name">{p.name}</span>
              <span>{p.age} y · {p.sex}</span>
              <span className="muted">MRN {p.mrn}</span>
              <span>{enc.ward} · {enc.bed}</span>
              <span className="muted">{enc.attending}</span>
              {stayDay ? <span className="pt-chip">Day {stayDay} of stay</span> : null}
              {p.code_status ? <span className={`pt-chip ${/dnr|dnar|not for/i.test(p.code_status) ? "pt-chip--danger" : ""}`}>{p.code_status}</span> : null}
            </div>
            <div className="pt-banner-row">
              <span className="pt-label">Allergies</span>
              {p.allergies.length
                ? p.allergies.map((a) => <span key={a} className="pt-chip pt-chip--danger">{a}</span>)
                : <span className="pt-chip pt-chip--ok">No known allergies</span>}
            </div>
            <div className="pt-banner-row">
              <span className="pt-label">Problems</span>
              {p.problems.length ? p.problems.map((x) => <span key={x} className="pt-chip">{x}</span>) : <span className="muted">None recorded</span>}
            </div>
          </>
        )}
      </section>

      {/* MUST: vitals in one line */}
      <section className="pt-vitals-row" aria-label="Latest vitals">
        <span className="pt-label">Vitals {s?.vitals ? `· ${when(s.vitals.occurred_at)}` : ""}</span>
        {!s ? <Skeleton count={1} /> : s.vitals ? VITALS.map((v) => {
          const value = vitalValue(s.vitals!.payload ?? {}, v.key);
          return <span key={v.key} className="pt-vital"><span className="muted">{v.label}</span> <b>{value ?? "–"}</b>{value ? <span className="muted"> {v.unit}</span> : null}</span>;
        }) : <span className="muted">No vitals documented.</span>}
      </section>

      {/* MUST: needs attention */}
      <section className="his-box">
        <h2 className="his-box-title">Needs attention {attention.length ? `(${attention.length})` : ""}</h2>
        {!s ? <Skeleton variant="rows" count={3} /> : attention.length === 0 ? (
          <p className="his-box-empty">Nothing needs attention right now.</p>
        ) : (
          <>
            <table className="table">
              <tbody>
                {attention.slice(0, ATTENTION_LIMIT).map((r) => (
                  <tr key={r.key}>
                    <td className={`strong his-tone-${r.tone}`}>{r.type}</td>
                    <td>{r.item}</td><td className="muted">{r.detail}</td>
                    <td className="right"><Link className="btn btn-sm" to={r.to}>{r.action}</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {attention.length > ATTENTION_LIMIT ? <Link className="pt-more" to="/safety?tab=alerts">View all ({attention.length}) →</Link> : null}
          </>
        )}
      </section>

      {/* MUST: care so far, from every input */}
      <section className="his-box">
        <h2 className="his-box-title">Care so far</h2>
        {!s ? <Skeleton variant="rows" count={6} /> : (
          <ul className="pt-care">
            {care.map((c) => (
              <li key={c.key} className={c.text ? "" : "pt-care--empty"}>
                <span className="pt-care-label">{c.label}</span>
                <span className="pt-care-text">{c.text ? clip(c.text) : "Not yet recorded"}</span>
                <span className="muted pt-care-when">{c.at ? when(c.at) : ""}</span>
                <Link className="pt-care-go" to={c.to} aria-label={`Open ${c.label}`}>→</Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* SHOULD: medicines + abnormal labs */}
      <div className="his-dash-cols">
        <section className="his-box">
          <h2 className="his-box-title">Current medicines {s ? `(${s.active_meds.length})` : ""}</h2>
          {!s ? <Skeleton variant="rows" count={4} /> : s.active_meds.length ? (
            <ul className="pt-list">
              {s.active_meds.slice(0, MEDS_LIMIT).map((m) => (
                <li key={m.event_id}><b>{m.drug}</b> <span className="muted">{[m.dose, m.route, m.frequency].filter(Boolean).join(" · ")}</span></li>
              ))}
              {s.active_meds.length > MEDS_LIMIT ? <li><Link to="/safety?tab=meds">+ {s.active_meds.length - MEDS_LIMIT} more</Link></li> : null}
            </ul>
          ) : <p className="his-box-empty">No active medicine orders.</p>}
        </section>

        <section className="his-box">
          <h2 className="his-box-title">Abnormal results</h2>
          {!s ? <Skeleton count={3} /> : abnormalLabs.length ? (
            <div className="pt-chips">
              {abnormalLabs.map((l) => (
                <span key={l.event_id} className="pt-chip pt-chip--danger">{l.name} {l.value} {l.unit} {l.flag === "high" ? "↑" : "↓"}</span>
              ))}
            </div>
          ) : <p className="his-box-empty">All latest results within range.</p>}
        </section>
      </div>

      {/* SHOULD: status counts */}
      <div className="pt-tiles">
        {kpis.map((k) => (
          <Link key={k.key} to={k.to} className="pt-tile">
            <span className="muted">{k.label}</span>
            <b className={k.tone ? `his-tone-${k.tone}` : ""}>{k.value}</b>
            <span className="muted">{k.note}</span>
          </Link>
        ))}
      </div>

      {progress.data ? (
        <Link to="/progress" className="pr-strip">
          <b>OVERALL PROGRESS: {progress.data.overall.percent}%</b>
          <span>{progress.data.overall.done} of {progress.data.overall.total} checks done</span>
          <span>TODAY: {progress.data.daily.tasks_done}/{progress.data.daily.tasks_total} tasks, {progress.data.daily.notes_verified}/{progress.data.daily.notes_total} notes verified</span>
          <span className="pr-strip-go">View progress &rarr;</span>
        </Link>
      ) : null}

      {/* COULD: full detail, collapsed */}
      <Disclosure title={`Full details${s ? ` (${s.latest_labs.length} results, ${s.active_meds.length} medicines, ${notes.length} notes)` : ""}`}>
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
            <h2 className="his-box-title">Recent notes</h2>
            {!s ? <Skeleton variant="rows" count={3} /> : notes.length ? (
              <table className="table">
                <tbody>
                  {notes.slice(0, 8).map((note) => (
                    <tr key={note.event_id}><td>{note.title}</td><td className="muted">{when(note.occurred_at)}</td><td className="right"><Link className="btn btn-sm" to="/timeline">Open</Link></td></tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="his-box-empty">No signed notes yet.</p>}
            {p?.weight_kg || p?.height_cm ? <p className="muted">Weight {p.weight_kg ?? "–"} kg · Height {p.height_cm ?? "–"} cm</p> : null}
          </section>
        </div>
      </Disclosure>
    </div>
  );
}
