import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post } from "../api";
import type { AppTask, Meta } from "../types";
import { useEvidence } from "../components/Evidence";
import { ReasonForm } from "../features/f15/ReasonForm";
import type { ReasonTarget } from "../features/f15/types";
import { Banner, Skeleton } from "../components/ui";
import { STAFF } from "../components/legacy/HisChrome";

const CATEGORIES: { key: string; label: string }[] = [
  { key: "general", label: "General" },
  { key: "lab", label: "Lab report" },
  { key: "ct", label: "CT scan" },
  { key: "mri", label: "MRI" },
  { key: "xray", label: "X-ray" },
  { key: "ultrasound", label: "Ultrasound" },
  { key: "ecg", label: "ECG" },
];
const CATEGORY_LABEL = Object.fromEntries(CATEGORIES.map((c) => [c.key, c.label]));
const ROLE_LABEL: Record<string, string> = { senior_doctor: "Senior doctor", nurse: "Nurse", doctor: "Chief doctor" };
const ASSIGNABLE = STAFF.filter((s) => s.role !== "doctor");

const STATUS_LABEL: Record<string, string> = {
  proposed: "PROPOSED",
  accepted: "ASSIGNED",
  acknowledged: "ACKNOWLEDGED",
  in_progress: "IN PROGRESS",
  completed: "DONE",
  cancelled: "CANCELLED",
};

type View = "open" | "done" | "all";

const isUrgent = (t: AppTask) => t.priority === "urgent" || t.priority === "critical";
const isOpen = (t: AppTask) => !["completed", "cancelled"].includes(t.status);
const due = (v?: string | null) =>
  v ? new Date(v).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "-";

export function TasksPage() {
  const queryClient = useQueryClient();
  const { showEvent } = useEvidence();
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta") });
  const tasks = useQuery<{ tasks: AppTask[] }>({ queryKey: ["tasks"], queryFn: () => get("/tasks") });

  const role = meta.data?.user?.role || "doctor";
  const me = meta.data?.user?.name || "";
  const isChief = role === "doctor";

  // assignment form (chief only)
  const [title, setTitle] = useState("");
  const [detail, setDetail] = useState("");
  const [assignee, setAssignee] = useState(ASSIGNABLE[0].id);
  const [category, setCategory] = useState("general");
  const [priority, setPriority] = useState<"routine" | "urgent">("routine");
  const [dueHours, setDueHours] = useState(4);

  const [view, setView] = useState<View>("open");
  const [roleFilter, setRoleFilter] = useState<"all" | "senior_doctor" | "nurse">("all");
  const [reasonFor, setReasonFor] = useState<ReasonTarget | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const done = (message: string) => () => {
    setError("");
    setNotice(message);
    setReasonFor(null);
    queryClient.invalidateQueries();
  };
  const failed = (err: unknown) => setError(String((err as Error)?.message || err));

  const create = useMutation({
    mutationFn: () => {
      const staff = ASSIGNABLE.find((s) => s.id === assignee)!;
      return post("/tasks", {
        title: title.trim(),
        detail: detail.trim(),
        owner: staff.name,
        assignee_role: staff.role,
        category,
        priority,
        due_in_hours: dueHours,
      });
    },
    onSuccess: () => {
      setTitle("");
      setDetail("");
      setPriority("routine");
      done("Task assigned.")();
    },
    onError: failed,
  });
  const status = useMutation({
    mutationFn: ({ id, to }: { id: string; to: string }) =>
      to === "acknowledged" ? post(`/tasks/${id}/acknowledge`, {}) : patch(`/tasks/${id}`, { status: to }),
    onSuccess: (_d, v) => done(v.to === "completed" ? "Task completed and added to the patient chart." : "Task updated.")(),
    onError: failed,
  });
  const urgent = useMutation({
    mutationFn: (id: string) => post(`/tasks/${id}/urgent`, {}),
    onSuccess: done("Marked urgent and moved to the top of the queue."),
    onError: failed,
  });
  const escalate = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => post(`/tasks/${id}/escalate`, { reason }),
    onSuccess: done("Escalation recorded."),
    onError: failed,
  });
  const reopen = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => post(`/tasks/${id}/reopen`, { reason }),
    onSuccess: done("Task reopened."),
    onError: failed,
  });
  const busy = create.isPending || status.isPending || urgent.isPending || escalate.isPending || reopen.isPending;

  // The server already filters by role and returns queue order (bumped, urgent, earliest due).
  const all = tasks.data?.tasks ?? [];
  const rows = all
    .filter((t) => (view === "open" ? isOpen(t) : view === "done" ? !isOpen(t) : true))
    .filter((t) => roleFilter === "all" || t.assignee_role === roleFilter);
  const openCount = all.filter(isOpen).length;
  const urgentCount = all.filter((t) => isOpen(t) && isUrgent(t)).length;
  const overdueCount = all.filter((t) => isOpen(t) && t.is_overdue).length;

  const actions = (t: AppTask) => {
    const out: JSX.Element[] = [];
    if (t.status === "proposed" && isChief) out.push(<button key="a" className="btn btn-sm" onClick={() => status.mutate({ id: t.id, to: "accepted" })}>Accept</button>);
    if (t.status === "accepted") out.push(<button key="k" className="btn btn-sm" onClick={() => status.mutate({ id: t.id, to: "acknowledged" })}>Acknowledge</button>);
    if (t.status === "acknowledged") out.push(<button key="s" className="btn btn-sm" onClick={() => status.mutate({ id: t.id, to: "in_progress" })}>Start</button>);
    if (t.status === "acknowledged" || t.status === "in_progress") out.push(<button key="c" className="btn btn-sm btn-primary" onClick={() => status.mutate({ id: t.id, to: "completed" })}>Complete</button>);
    if (isOpen(t) && isChief && !(isUrgent(t) && all.filter(isOpen)[0]?.id === t.id)) {
      out.push(<button key="u" className="btn btn-sm tk-urgent-btn" onClick={() => urgent.mutate(t.id)} title="Mark urgent and move to the top of the queue">Urgent</button>);
    }
    if (isOpen(t) && isChief) out.push(<button key="e" className="btn btn-sm" onClick={() => setReasonFor({ id: t.id, mode: "escalate" })}>Escalate</button>);
    if (t.status === "completed" && t.completion_event_id) out.push(<button key="v" className="btn btn-sm" onClick={() => showEvent(t.completion_event_id!)}>In chart</button>);
    if (!isOpen(t)) out.push(<button key="r" className="btn btn-sm" onClick={() => setReasonFor({ id: t.id, mode: "reopen" })}>Reopen</button>);
    return out;
  };

  return (
    <div className="page dc-his tk-page">
      <section className="dc-form" aria-label="Task header">
        <div className="dc-form-top">
          <div className="tk-counts">
            <span><b>{openCount}</b> OPEN</span>
            <span className="tk-red"><b>{urgentCount}</b> URGENT</span>
            <span><b>{overdueCount}</b> OVERDUE</span>
          </div>
          <h1 className="dc-form-title">Tasks &amp; Escalation</h1>
          <div className="dc-form-tools tk-who">
            {ROLE_LABEL[role] || role}: <b>{me}</b>
          </div>
        </div>

        {isChief ? (
          <form
            className="field-grid-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (title.trim().length >= 3) create.mutate();
            }}
          >
            <label className="gf gf-wide">
              <span className="gf-label">Task</span>
              <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. CT head without contrast, report to chief" required minLength={3} />
            </label>
            <label className="gf">
              <span className="gf-label">Assign to</span>
              <select className="select" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                {ASSIGNABLE.map((s) => <option key={s.id} value={s.id}>{s.label}: {s.name}</option>)}
              </select>
            </label>
            <label className="gf gf-wide">
              <span className="gf-label">Detail</span>
              <input className="input" value={detail} onChange={(e) => setDetail(e.target.value)} placeholder="Instructions for the assignee" />
            </label>
            <label className="gf">
              <span className="gf-label">Type</span>
              <select className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORIES.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
              </select>
            </label>
            <div className="gf">
              <span className="gf-label">Priority</span>
              <div className="dc-radios tk-prio">
                <label className="tk-green"><input type="radio" name="tk-prio" checked={priority === "routine"} onChange={() => setPriority("routine")} /> Normal</label>
                <label className="tk-red"><input type="radio" name="tk-prio" checked={priority === "urgent"} onChange={() => setPriority("urgent")} /> Urgent</label>
              </div>
            </div>
            <label className="gf">
              <span className="gf-label">Due in (hrs)</span>
              <input className="input" type="number" min={1} max={168} value={dueHours} onChange={(e) => setDueHours(Number(e.target.value) || 1)} />
            </label>
            <div className="gf tk-submit">
              <span className="gf-label" />
              <button type="submit" className="btn btn-primary" disabled={busy || title.trim().length < 3}>
                {create.isPending ? "Assigning..." : "Assign task"}
              </button>
            </div>
          </form>
        ) : (
          <p className="tk-note">You see the tasks assigned to you as {ROLE_LABEL[role] || role}. Acknowledge, start and complete them here; finished tasks go into the patient chart.</p>
        )}
      </section>

      {error ? <Banner tone="danger" role="alert">{error}</Banner> : null}
      {notice && !error ? <Banner tone="success" role="status">{notice}</Banner> : null}

      <div className="tk-bar">
        <div className="tabs" role="tablist" aria-label="Task view">
          {(["open", "done", "all"] as View[]).map((v) => (
            <button key={v} type="button" role="tab" className="tab" aria-selected={view === v} onClick={() => setView(v)}>
              {v === "open" ? "Task Queue" : v === "done" ? "Completed" : "All Tasks"}
            </button>
          ))}
        </div>
        {isChief ? (
          <label className="tk-filter">
            SHOW
            <select className="select" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value as typeof roleFilter)}>
              <option value="all">All staff</option>
              <option value="senior_doctor">Senior doctors</option>
              <option value="nurse">Nurses</option>
            </select>
          </label>
        ) : null}
      </div>

      <div className="dc-tabbody">
        {tasks.isLoading ? <div className="dc-pad"><Skeleton count={5} /></div> : rows.length ? (
          <table className="table dc-grid tk-grid">
            <thead>
              <tr>
                <th style={{ width: 36 }}>#</th>
                <th>Priority</th>
                <th>Type</th>
                <th>Task</th>
                <th>Assigned to</th>
                <th>Due</th>
                <th>Status</th>
                <th className="right">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t, i) => (
                <Fragment key={t.id}>
                  <tr className={isUrgent(t) && isOpen(t) ? "tk-row-urgent" : ""}>
                    <td>{i + 1}</td>
                    <td><span className={`tk-tag ${isUrgent(t) ? "red" : "green"}`}>{isUrgent(t) ? "URGENT" : "NORMAL"}</span></td>
                    <td className="nowrap">{CATEGORY_LABEL[t.category || "general"] || t.category}</td>
                    <td>
                      <div className="tk-title">{t.title}</div>
                      {t.detail ? <div className="muted small">{t.detail}</div> : null}
                      {t.escalation_level ? <div className="small tk-red">Escalated (level {t.escalation_level}){t.escalation_reason ? `: ${t.escalation_reason}` : ""}</div> : null}
                    </td>
                    <td>
                      <div>{t.assigned_to || "-"}</div>
                      <div className="muted small">{ROLE_LABEL[t.assignee_role || ""] || ""}</div>
                    </td>
                    <td className={`nowrap ${t.is_overdue ? "tk-red strong" : ""}`}>{due(t.due_at)}{t.is_overdue ? " (overdue)" : ""}</td>
                    <td className="nowrap"><span className={`tk-status s-${t.status}`}>{STATUS_LABEL[t.status] || t.status}</span></td>
                    <td className="right"><div className="tk-actions">{actions(t)}</div></td>
                  </tr>
                  {reasonFor?.id === t.id ? (
                    <tr className="row-detail">
                      <td colSpan={8}>
                        <ReasonForm
                          mode={reasonFor.mode}
                          busy={busy}
                          onCancel={() => setReasonFor(null)}
                          onConfirm={(reason) => (reasonFor.mode === "escalate" ? escalate : reopen).mutate({ id: t.id, reason })}
                        />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="his-box-empty">{view === "open" ? "No open tasks in the queue." : "No tasks to show."}</p>
        )}
      </div>
    </div>
  );
}
