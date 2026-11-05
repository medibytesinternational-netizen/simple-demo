import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "../api";
import { useEvidence } from "../components/Evidence";
import { usePatientId } from "../session";
import { Skeleton } from "../components/ui";

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

const Tag = ({ s }: { s: string }) => {
  const t = STATUS_TAG[s] || { cls: "grey", text: s.toUpperCase() };
  return <span className={`tk-tag ${t.cls}`}>{t.text}</span>;
};
function Bar({ label, done, total, note }: { label: string; done: number; total: number; note: string }) {
  const pct = total ? Math.round((100 * done) / total) : 0;
  const tone = !total ? "empty" : pct === 100 ? "full" : pct >= 50 ? "mid" : "low";
  return (
    <div className="pr-meter">
      <div className="pr-meter-head">
        <b>{label}</b>
        <span>{total ? `${pct}% · ${note}` : "Nothing to track for this day"}</span>
      </div>
      <div className="pr-meter-track" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <div className={`pr-meter-fill t-${tone}`} style={{ width: `${pct}%` }}>{pct >= 8 ? `${pct}%` : ""}</div>
      </div>
    </div>
  );
}

const time = (v?: string | null) => (v ? new Date(v).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "-");
const longDay = (v: string) => new Date(`${v}T00:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });

export function ProgressPage() {
  const patientId = usePatientId();
  const { showEvent } = useEvidence();
  const [tab, setTab] = useState<"overall" | "daily">("overall");
  const [day, setDay] = useState<string | null>(null);

  const progress = useQuery<ProgressResponse>({
    queryKey: ["progress", patientId, day],
    queryFn: () => get(`/patients/${patientId}/progress${day ? `?date=${day}` : ""}`),
    enabled: !!patientId,
    placeholderData: (previous) => previous,
  });
  const data = progress.data;
  const days = data?.days ?? [];
  const current = data?.daily.date ?? day ?? "";
  const idx = days.indexOf(current);
  const step = (by: number) => {
    const next = days[idx + by];
    if (next) setDay(next);
  };

  return (
    <div className="page dc-his pg-progress">
      <section className="dc-form" aria-label="Patient progress header">
        <div className="dc-form-top">
          <div className="pr-score">
            {data ? (
              <>
                <span className="pr-pct">{data.overall.percent}%</span>
                <span>OVERALL &middot; {data.overall.done} of {data.overall.total} checks done</span>
              </>
            ) : <span>Loading...</span>}
          </div>
          <h1 className="dc-form-title">Patient Progress</h1>
          <div className="dc-form-tools">
            {tab === "daily" && data ? (
              <div className="pr-day" aria-label="Day">
                <button type="button" className="btn btn-sm" onClick={() => step(-1)} disabled={idx <= 0} aria-label="Previous day">&#9664;</button>
                <select className="select" value={current} onChange={(e) => setDay(e.target.value)} aria-label="Choose a day">
                  {(days.includes(current) ? days : [...days, current]).map((d, i) => <option key={d} value={d}>Day {i + 1}: {longDay(d)}</option>)}
                </select>
                <button type="button" className="btn btn-sm" onClick={() => step(1)} disabled={idx < 0 || idx >= days.length - 1} aria-label="Next day">&#9654;</button>
              </div>
            ) : null}
          </div>
        </div>
        {data ? (
          <div className="pr-bar" role="img" aria-label={`${data.overall.percent}% of the stay is complete and verified`}>
            {data.overall.stages.map((s) => (
              <span key={s.key} className={`pr-seg s-${s.status}`} title={`${s.title}: ${s.status}`}>{s.title}</span>
            ))}
          </div>
        ) : <Skeleton count={1} />}
      </section>

      <div className="tabs" role="tablist" aria-label="Progress view">
        <button type="button" role="tab" className="tab" aria-selected={tab === "overall"} onClick={() => setTab("overall")}>Overall Progress</button>
        <button type="button" role="tab" className="tab" aria-selected={tab === "daily"} onClick={() => setTab("daily")}>Daily Progress</button>
      </div>

      <div className="dc-tabbody pr-body">
        {!data ? <div className="dc-pad"><Skeleton count={6} /></div> : tab === "overall" ? (
          <>
          <Bar label="OVERALL PROGRESS" done={data.overall.done} total={data.overall.total} note={`${data.overall.done} of ${data.overall.total} checks done and verified`} />
          <table className="table dc-grid">
            <thead><tr><th style={{ width: "18%" }}>Stage</th><th>Check</th><th style={{ width: 100 }}>Status</th><th>Detail</th><th /></tr></thead>
            <tbody>
              {data.overall.stages.map((stage) => stage.checks.map((c, i) => (
                <tr key={`${stage.key}-${c.key}`} className={i === 0 ? "pr-stage-first" : ""}>
                  <td>{i === 0 ? <>{stage.title.toUpperCase()} <Tag s={stage.status} /></> : ""}</td>
                  <td className="pr-check">{c.label}</td>
                  <td><Tag s={c.status} /></td>
                  <td className="muted">{c.detail}</td>
                  <td className="right">{c.status !== "done" ? <Link className="btn btn-sm" to={c.link}>Open</Link> : null}</td>
                </tr>
              )))}
            </tbody>
          </table>
          </>
        ) : (
          <div className="pr-daily">
            <Bar
              label="DAILY PROGRESS"
              done={data.daily.tasks_done + data.daily.notes_verified}
              total={data.daily.tasks_total + data.daily.notes_total}
              note={`${data.daily.tasks_done + data.daily.notes_verified} of ${data.daily.tasks_total + data.daily.notes_total} items done`}
            />
            <div className="pr-sub-meters">
              <Bar label="Tasks completed" done={data.daily.tasks_done} total={data.daily.tasks_total} note={`${data.daily.tasks_done} of ${data.daily.tasks_total}`} />
              <Bar label="Notes verified" done={data.daily.notes_verified} total={data.daily.notes_total} note={`${data.daily.notes_verified} of ${data.daily.notes_total}`} />
            </div>
            <p className={`pr-summary ${data.daily.complete ? "ok" : ""}`}>
              {longDay(data.daily.date)} &middot; {data.daily.tasks_done} of {data.daily.tasks_total} tasks completed &middot; {data.daily.notes_verified} of {data.daily.notes_total} notes verified
              {data.daily.complete && (data.daily.tasks_total || data.daily.notes_total) ? " · DAY COMPLETE" : ""}
            </p>

            <h2 className="his-box-title">Tasks for the day</h2>
            {data.daily.tasks.length ? (
              <table className="table dc-grid">
                <thead><tr><th>Task</th><th>Type</th><th>Assigned to</th><th>Due</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {data.daily.tasks.map((t) => (
                    <tr key={t.id}>
                      <td>{t.title}{t.priority === "urgent" || t.priority === "critical" ? <span className="pr-urgent"> URGENT</span> : null}</td>
                      <td className="muted">{CATEGORY[t.category] || t.category}</td>
                      <td>{t.assigned_to || "-"} <span className="muted small">{ROLE[t.assignee_role || ""] || ""}</span></td>
                      <td className="muted">{time(t.due_at)}</td>
                      <td><Tag s={t.state} /></td>
                      <td className="right">
                        {t.completion_event_id ? <button type="button" className="btn btn-sm" onClick={() => showEvent(t.completion_event_id!)}>In chart</button>
                          : t.state !== "done" && t.state !== "cancelled" ? <Link className="btn btn-sm" to="/tasks">Open</Link> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="his-box-empty">No tasks due or completed on this day.</p>}

            <h2 className="his-box-title">Notes &amp; records for the day</h2>
            {data.daily.notes.length ? (
              <table className="table dc-grid">
                <thead><tr><th>Record</th><th>Title</th><th>By</th><th>Time</th><th>Status</th></tr></thead>
                <tbody>
                  {data.daily.notes.map((n) => (
                    <tr key={n.id}>
                      <td>{n.kind}</td>
                      <td>{n.state === "verified" ? <button type="button" className="lrow-title-btn pr-link" onClick={() => showEvent(n.id)}>{n.title}</button> : n.title}</td>
                      <td className="muted">{n.author || "-"}</td>
                      <td className="muted">{time(n.at)}</td>
                      <td><Tag s={n.state} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="his-box-empty">No notes or records on this day.</p>}
          </div>
        )}
      </div>
    </div>
  );
}
