import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "../api";
import { formatHospitalDateTime, formatHospitalTime } from "../dates";
import { useEvidence } from "../components/Evidence";
import { usePatientId } from "../session";
import { Disclosure, Skeleton } from "../components/ui";

// Patient Progress, laid out by MoSCoW:
// Must   = score + stage stepper, what is still to do, today's open work
// Should = today's notes and completed tasks
// Could  = completed checks (collapsed)

type CheckStatus = "done" | "pending" | "missing";
type Check = { key: string; label: string; status: CheckStatus; detail: string; link: string };
type Stage = { key: string; title: string; status: CheckStatus; checks: Check[] };
type DailyTask = {
  id: string; title: string; category: string; priority: string; assigned_to?: string | null;
  assignee_role?: string | null; due_at?: string | null; status: string;
  state: "done" | "open" | "overdue" | "cancelled"; completion_event_id?: string | null;
};
type DailyNote = { id: string; kind: string; title: string; author?: string | null; at?: string | null; state: "verified" | "pending" };
export type ProgressResponse = {
  overall: { stages: Stage[]; done: number; total: number; percent: number };
  daily: {
    date: string; tasks: DailyTask[]; notes: DailyNote[];
    tasks_done: number; tasks_total: number; notes_verified: number; notes_total: number; complete: boolean;
  };
  days: string[];
};

const STATUS_TAG: Record<string, { cls: string; text: string }> = {
  done: { cls: "green", text: "DONE" },
  verified: { cls: "green", text: "VERIFIED" },
  pending: { cls: "amber", text: "PENDING" },
  open: { cls: "amber", text: "OPEN" },
  missing: { cls: "red", text: "MISSING" },
  overdue: { cls: "red", text: "OVERDUE" },
  cancelled: { cls: "grey", text: "CANCELLED" },
};
const ROLE: Record<string, string> = { senior_doctor: "Senior doctor", nurse: "Nurse" };
const CATEGORY: Record<string, string> = { general: "General", lab: "Lab report", ct: "CT scan", mri: "MRI", xray: "X-ray", ultrasound: "Ultrasound", ecg: "ECG" };
const OPEN_TASK_LIMIT = 5;
const NOTES_LIMIT = 6;

const Tag = ({ s }: { s: string }) => {
  const t = STATUS_TAG[s] || { cls: "grey", text: s.toUpperCase() };
  return <span className={`tk-tag ${t.cls}`}>{t.text}</span>;
};

const time = (v?: string | null) => (v ? formatHospitalTime(v, "en-GB") : "-");
const longDay = (v: string) => formatHospitalDateTime(v, "en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });

export function ProgressPage() {
  const patientId = usePatientId();
  const { showEvent } = useEvidence();
  const [day, setDay] = useState<string | null>(null);
  const [showAllNotes, setShowAllNotes] = useState(false);

  const progress = useQuery<ProgressResponse>({
    queryKey: ["progress", patientId, day],
    queryFn: () => get(`/patients/${patientId}/progress${day ? `?date=${day}` : ""}`),
    enabled: !!patientId,
    placeholderData: (previous) => previous,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
  const data = progress.data;
  const days = data?.days ?? [];
  const current = data?.daily.date ?? day ?? "";
  const idx = days.indexOf(current);
  const step = (by: number) => {
    const next = days[idx + by];
    if (next) setDay(next);
  };

  const stages = data?.overall.stages ?? [];
  const rank = { missing: 0, pending: 1, done: 2 } as const;
  const todo = stages
    .flatMap((s) => s.checks.filter((c) => c.status !== "done").map((c) => ({ stage: s, check: c })))
    .sort((a, b) => rank[a.check.status] - rank[b.check.status]);
  const tasks = data?.daily.tasks ?? [];
  const openTasks = tasks
    .filter((t) => t.state === "open" || t.state === "overdue")
    .sort((a, b) => (a.state === b.state ? 0 : a.state === "overdue" ? -1 : 1));
  const doneTasks = tasks.filter((t) => t.state === "done");
  const overdue = openTasks.filter((t) => t.state === "overdue").length;

  const jump = (key: string) => document.getElementById(`pg-stage-${key}`)?.scrollIntoView({ behavior: "smooth", block: "center" });

  return (
    <div className="page his-dash pg-progress">
      <header className="page-header">
        <div className="page-header-text">
          <h1 className="page-h1">Patient Progress</h1>
          <p className="page-desc">Where the patient is in the stay, what is still to do, and what happened today.</p>
        </div>
      </header>

      {progress.isError ? <p className="error-box" role="alert">Progress could not be loaded. Try again in a moment.</p> : null}

      {/* MUST: score + stage stepper */}
      <section className="pt-banner" aria-label="Overall progress">
        {!data ? <Skeleton count={2} /> : (
          <>
            <div className="pg-score">
              <span className="pg-pct">{data.overall.percent}%</span>
              <span className="muted">{data.overall.done} of {data.overall.total} checks done and verified</span>
            </div>
            <ol className="pg-stepper">
              {stages.map((s) => {
                const done = s.checks.filter((c) => c.status === "done").length;
                return (
                  <li key={s.key}>
                    <button type="button" className={`pg-step pg-step--${s.status}`} onClick={() => jump(s.key)} title={`${s.title}: ${s.status}`}>
                      <span className="pg-step-dot" aria-hidden>{s.status === "done" ? "✓" : s.status === "missing" ? "!" : "…"}</span>
                      <span className="pg-step-name">{s.title}</span>
                      <span className="pg-step-count">{done}/{s.checks.length}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </>
        )}
      </section>

      {/* MUST: still to do */}
      <section className="his-box">
        <h2 className="his-box-title">Still to do {data ? `(${todo.length})` : ""}</h2>
        {!data ? <Skeleton variant="rows" count={4} /> : todo.length === 0 ? (
          <p className="his-box-empty">All checks complete.</p>
        ) : (
          <table className="table">
            <tbody>
              {todo.map(({ stage, check }) => (
                <tr key={`${stage.key}-${check.key}`} id={`pg-stage-${stage.key}`}>
                  <td style={{ width: 110 }}><Tag s={check.status} /></td>
                  <td className="muted" style={{ width: "18%" }}>{stage.title}</td>
                  <td className="strong">{check.label}</td>
                  <td className="muted">{check.detail}</td>
                  <td className="right"><Link className="btn btn-sm" to={check.link}>Open</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* MUST: today */}
      <section className="his-box">
        <div className="pg-today-head">
          <h2 className="his-box-title">{data ? `Day ${idx >= 0 ? idx + 1 : days.length} · ${longDay(current)}` : "Today"}</h2>
          {data ? (
            <span className="pg-today-counts">
              <span>Tasks <b>{data.daily.tasks_done}/{data.daily.tasks_total}</b></span>
              <span>Notes <b>{data.daily.notes_verified}/{data.daily.notes_total}</b></span>
              <span className={overdue ? "his-tone-critical" : ""}>Overdue <b>{overdue}</b></span>
              {data.daily.complete && (data.daily.tasks_total || data.daily.notes_total) ? <span className="pt-chip pt-chip--ok">Day complete</span> : null}
            </span>
          ) : null}
          {data ? (
            <div className="pr-day" aria-label="Day">
              <button type="button" className="btn btn-sm" onClick={() => step(-1)} disabled={idx <= 0} aria-label="Previous day">&#9664;</button>
              <select className="select" value={current} onChange={(e) => setDay(e.target.value)} aria-label="Choose a day">
                {(days.includes(current) ? days : [...days, current]).map((d, i) => <option key={d} value={d}>Day {i + 1}: {longDay(d)}</option>)}
              </select>
              <button type="button" className="btn btn-sm" onClick={() => step(1)} disabled={idx < 0 || idx >= days.length - 1} aria-label="Next day">&#9654;</button>
            </div>
          ) : null}
        </div>
        {!data ? <Skeleton variant="rows" count={3} /> : openTasks.length ? (
          <>
            <table className="table">
              <tbody>
                {openTasks.slice(0, OPEN_TASK_LIMIT).map((t) => (
                  <tr key={t.id}>
                    <td style={{ width: 110 }}><Tag s={t.state} /></td>
                    <td>{t.title}{t.priority === "urgent" || t.priority === "critical" ? <span className="pr-urgent"> URGENT</span> : null}</td>
                    <td className="muted">{CATEGORY[t.category] || t.category}</td>
                    <td className="muted">{t.assigned_to || "Unassigned"} {ROLE[t.assignee_role || ""] ? `· ${ROLE[t.assignee_role || ""]}` : ""}</td>
                    <td className="muted">due {time(t.due_at)}</td>
                    <td className="right"><Link className="btn btn-sm" to="/tasks">Open</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {openTasks.length > OPEN_TASK_LIMIT ? <Link className="pt-more" to="/tasks">View all ({openTasks.length}) →</Link> : null}
          </>
        ) : <p className="his-box-empty">No open tasks for this day.</p>}
      </section>

      {/* SHOULD: notes + completed tasks for the day */}
      <div className="his-dash-cols">
        <section className="his-box">
          <h2 className="his-box-title">Notes &amp; records {data ? `(${data.daily.notes.length})` : ""}</h2>
          {!data ? <Skeleton variant="rows" count={3} /> : data.daily.notes.length ? (
            <ul className="pt-list">
              {data.daily.notes.slice(0, showAllNotes ? undefined : NOTES_LIMIT).map((n) => (
                <li key={n.id} className="pg-row">
                  <Tag s={n.state} />
                  {n.state === "verified"
                    ? <button type="button" className="lrow-title-btn pr-link" onClick={() => showEvent(n.id)}>{n.title}</button>
                    : <span>{n.title}</span>}
                  <span className="muted">{n.kind} · {n.author || "-"} · {time(n.at)}</span>
                </li>
              ))}
            </ul>
          ) : <p className="his-box-empty">No notes or records on this day.</p>}
          {data && data.daily.notes.length > NOTES_LIMIT ? (
            <button type="button" className="pt-more btn-link" onClick={() => setShowAllNotes((v) => !v)}>
              {showAllNotes ? "Show fewer" : `Show all (${data.daily.notes.length}) →`}
            </button>
          ) : null}
        </section>

        <section className="his-box">
          <h2 className="his-box-title">Completed tasks {data ? `(${doneTasks.length})` : ""}</h2>
          {!data ? <Skeleton variant="rows" count={3} /> : doneTasks.length ? (
            <ul className="pt-list">
              {doneTasks.map((t) => (
                <li key={t.id} className="pg-row">
                  <Tag s="done" />
                  <span>{t.title}</span>
                  <span className="muted">{t.assigned_to || "-"}</span>
                  {t.completion_event_id ? <button type="button" className="btn btn-sm" onClick={() => showEvent(t.completion_event_id!)}>In chart</button> : null}
                </li>
              ))}
            </ul>
          ) : <p className="his-box-empty">No tasks completed on this day.</p>}
        </section>
      </div>

      {/* COULD: completed checks */}
      {data ? (
        <Disclosure title={`Completed checks (${data.overall.done})`}>
          <table className="table">
            <tbody>
              {stages.flatMap((s) => s.checks.filter((c) => c.status === "done").map((c) => (
                <tr key={`${s.key}-${c.key}`} id={s.status === "done" ? `pg-stage-${s.key}` : undefined}>
                  <td style={{ width: 110 }}><Tag s="done" /></td>
                  <td className="muted" style={{ width: "18%" }}>{s.title}</td>
                  <td>{c.label}</td>
                  <td className="muted">{c.detail}</td>
                </tr>
              )))}
            </tbody>
          </table>
        </Disclosure>
      ) : null}
    </div>
  );
}
