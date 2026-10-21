import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post } from "../api";
import type { AppTask, Meta } from "../types";
import { useEvidence } from "../components/Evidence";
import { ReasonForm } from "../features/f15/ReasonForm";
import { canAcknowledge, escalationKind, isClosed } from "../features/f15/rules";
import type { ReasonTarget } from "../features/f15/types";

const FILTERS = ["all", "open", "overdue", "completed"] as const;

const statusBadge: Record<string, string> = {
  proposed: "badge-neutral",
  accepted: "badge-ai",
  acknowledged: "badge-ai",
  in_progress: "badge-warning",
  completed: "badge-success",
  cancelled: "badge-neutral",
};

const ASSIGNEES = ["Dr. Meera Shah", "Nurse Anita Rao", "Pharmacist Dev Patel", "Billing desk"];

export function TasksPage() {
  const queryClient = useQueryClient();
  const { showEvent } = useEvidence();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("open");
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("routine");
  const [dueHours, setDueHours] = useState(24);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reasonFor, setReasonFor] = useState<ReasonTarget | null>(null);

  const tasks = useQuery<{ tasks: AppTask[] }>({ queryKey: ["tasks"], queryFn: () => get("/tasks") });
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  const userName = meta.data?.user?.name;

  const update = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => patch(`/tasks/${id}`, { status }),
    onMutate: () => setError(""),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const assign = useMutation({
    mutationFn: ({ id, assigned_to }: { id: string; assigned_to: string }) => post(`/tasks/${id}/assign`, { assigned_to }),
    onSuccess: () => {
      setNotice("Assignment recorded and audited.");
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const acknowledge = useMutation({
    mutationFn: (id: string) => post(`/tasks/${id}/acknowledge`, {}),
    onMutate: () => setError(""),
    onSuccess: () => {
      setNotice("Task acknowledged by the assigned owner.");
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const escalate = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => post(`/tasks/${id}/escalate`, { reason }),
    onMutate: () => setError(""),
    onSuccess: () => {
      setNotice("Escalation recorded with your reason.");
      setReasonFor(null);
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const reopen = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => post(`/tasks/${id}/reopen`, { reason }),
    onMutate: () => setError(""),
    onSuccess: () => {
      setNotice("Task reopened. It needs to be acknowledged again.");
      setReasonFor(null);
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const runEscalations = useMutation({
    mutationFn: () => post<{ count: number }>("/tasks/escalations/run", {}),
    onSuccess: (result) => {
      setNotice(`${result.count} task${result.count === 1 ? "" : "s"} escalated by the overdue sweep.`);
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const create = useMutation({
    mutationFn: () => post("/tasks", { title, detail: "", priority, due_in_hours: dueHours }),
    onSuccess: () => {
      setTitle("");
      setError("");
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const all = tasks.data?.tasks || [];
  const filtered = all.filter((task) => {
    if (filter === "all") return true;
    if (filter === "open") return !["completed", "cancelled"].includes(task.status);
    if (filter === "overdue") return task.is_overdue;
    return ["completed", "cancelled"].includes(task.status);
  });
  const overdue = all.filter((task) => task.is_overdue).length;
  const accepted = all.filter((task) => ["accepted", "acknowledged", "in_progress"].includes(task.status)).length;
  const escalated = all.filter((task) => (task.escalation_level || 0) > 0).length;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Tasks</h1>
          <div className="page-sub">
            Proposed tasks are not real until accepted. Every transition is audited. Overdue is computed against the demo clock, not hand-set.
          </div>
        </div>
        <div className="page-actions">
          <span className="badge badge-neutral">{all.length} total</span>
          <span className="badge badge-warning">{overdue} overdue</span>
          <span className="badge badge-critical">{escalated} escalated</span>
          <button className="btn btn-sm" onClick={() => runEscalations.mutate()} disabled={runEscalations.isPending}>
            {runEscalations.isPending ? "Running…" : "Run escalation sweep"}
          </button>
        </div>
      </div>

      <div className="grid-4 mb-3">
        <div className="card stat"><div className="stat-label">Active</div><div className="stat-value">{accepted}</div><div className="stat-note">Accepted, acknowledged or in progress</div></div>
        <div className="card stat"><div className="stat-label">Overdue</div><div className="stat-value" style={{ color: overdue ? "var(--warning)" : undefined }}>{overdue}</div><div className="stat-note">Past due and still open</div></div>
        <div className="card stat"><div className="stat-label">Escalated</div><div className="stat-value" style={{ color: escalated ? "var(--critical)" : undefined }}>{escalated}</div><div className="stat-note">Level 1 or 2, with reason and timestamp</div></div>
        <div className="card stat"><div className="stat-label">Completed</div><div className="stat-value">{all.filter((task) => task.status === "completed").length}</div><div className="stat-note">With completion timestamp</div></div>
      </div>

      {error ? <div className="error-box mb-3">{error}</div> : null}
      {notice ? <div className="success-box mb-3">{notice}</div> : null}

      <div className="card mb-3">
        <div className="card-head">
          <div className="card-title">Task list</div>
          <div className="subtabs" style={{ margin: 0 }}>
            {FILTERS.map((item) => (
              <button key={item} className={`btn btn-sm ${filter === item ? "btn-primary" : ""}`} onClick={() => setFilter(item)}>
                {item}
              </button>
            ))}
          </div>
        </div>
        <table className="table">
          <thead><tr><th>Task</th><th>Priority</th><th>Status</th><th>Due</th><th>Owner</th><th className="right">Actions</th></tr></thead>
          <tbody>
            {filtered.map((task) => (
              <Fragment key={task.id}>
              <tr>
                <td>
                  <div style={{ fontWeight: 550 }}>{task.title}</div>
                  <div className="small muted">
                    {task.accepted_from_draft_id ? "accepted from round draft" : task.source_event_id ? "from timeline" : "manual"}
                    {task.source_event_id ? (
                      <button className="btn btn-ghost btn-sm" style={{ padding: "0 4px", fontSize: 10 }} onClick={() => showEvent(task.source_event_id!)}>
                        source
                      </button>
                    ) : null}
                  </div>
                </td>
                <td><span className={`badge ${task.priority === "critical" ? "badge-critical" : task.priority === "urgent" ? "badge-warning" : "badge-neutral"}`}>{task.priority}</span></td>
                <td>
                  <span className={`badge ${statusBadge[task.status] || "badge-neutral"}`}>{task.status.replaceAll("_", " ")}</span>
                  {task.is_overdue ? <span className="badge badge-warning" style={{ marginLeft: 4 }}>overdue</span> : null}
                  {task.escalation_level ? (
                    <>
                      <span className="badge badge-critical" style={{ marginLeft: 4 }} title={task.escalation_reason || ""}>L{task.escalation_level}</span>
                      <span className="badge badge-neutral" style={{ marginLeft: 4 }}>{escalationKind(task)}</span>
                    </>
                  ) : null}
                  {task.escalation_level && task.escalation_reason ? <div className="small muted">{task.escalation_reason}</div> : null}
                  {task.acknowledged_at ? <div className="small muted">ack by {task.acknowledged_by}</div> : null}
                </td>
                <td className="mono small">{task.due_at ? new Date(task.due_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
                <td className="small">
                  <select
                    className="select"
                    style={{ padding: "3px 6px", fontSize: 11, minWidth: 140 }}
                    value={task.assigned_to || task.owner || ""}
                    onChange={(event) => assign.mutate({ id: task.id, assigned_to: event.target.value })}
                  >
                    <option value="">Unassigned</option>
                    {ASSIGNEES.map((person) => <option key={person} value={person}>{person}</option>)}
                  </select>
                  {task.assigned_at ? <div className="small muted">assigned</div> : null}
                </td>
                <td className="right">
                  <div className="button-row" style={{ justifyContent: "flex-end" }}>
                    {task.status === "proposed" ? <button className="btn btn-sm" onClick={() => update.mutate({ id: task.id, status: "accepted" })}>Accept</button> : null}
                    {task.status === "accepted" ? <button
                      className="btn btn-sm"
                      disabled={!canAcknowledge(task, userName)}
                      title={canAcknowledge(task, userName) ? "" : task.assigned_to ? `Only ${task.assigned_to} can acknowledge this task` : "Assign the task first"}
                      onClick={() => acknowledge.mutate(task.id)}
                    >
                      Acknowledge
                    </button> : null}
                    {task.status === "acknowledged" ? <button className="btn btn-sm" onClick={() => update.mutate({ id: task.id, status: "in_progress" })}>Start</button> : null}
                    {["acknowledged", "in_progress"].includes(task.status) ? <button className="btn btn-sm btn-primary" onClick={() => update.mutate({ id: task.id, status: "completed" })}>Complete</button> : null}
                    {!isClosed(task) && (task.escalation_level || 0) < 2 ? (
                      <button className="btn btn-ghost btn-sm" onClick={() => setReasonFor({ id: task.id, mode: "escalate" })}>Escalate</button>
                    ) : null}
                    {isClosed(task) ? (
                      <button className="btn btn-ghost btn-sm" onClick={() => setReasonFor({ id: task.id, mode: "reopen" })}>Reopen</button>
                    ) : null}
                    {!["completed", "cancelled"].includes(task.status) ? <button className="btn btn-ghost btn-sm" onClick={() => update.mutate({ id: task.id, status: "cancelled" })}>Cancel</button> : null}
                  </div>
                </td>
              </tr>
              {reasonFor?.id === task.id ? (
                <tr key={`${task.id}-reason`}>
                  <td colSpan={6}>
                    <ReasonForm
                      mode={reasonFor.mode}
                      busy={escalate.isPending || reopen.isPending}
                      onCancel={() => setReasonFor(null)}
                      onConfirm={(reason) => (reasonFor.mode === "escalate" ? escalate : reopen).mutate({ id: task.id, reason })}
                    />
                  </td>
                </tr>
              ) : null}
              </Fragment>
            ))}
            {!filtered.length ? <tr><td colSpan={6}><div className="empty">No tasks in this filter.</div></td></tr> : null}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="card-head"><div className="card-title">Add a task manually</div><span className="badge badge-neutral">creates as accepted</span></div>
        <div className="card-pad">
          <div className="form-row">
            <div style={{ flex: 2, minWidth: 240 }}>
              <label className="field-label">Task</label>
              <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Repeat potassium in 6 hours" />
            </div>
            <div>
              <label className="field-label">Priority</label>
              <select className="select" value={priority} onChange={(event) => setPriority(event.target.value)}>
                <option value="routine">routine</option>
                <option value="urgent">urgent</option>
                <option value="critical">critical</option>
              </select>
            </div>
            <div>
              <label className="field-label">Due in hours</label>
              <input className="input" type="number" min={1} value={dueHours} onChange={(event) => setDueHours(Number(event.target.value))} style={{ width: 110 }} />
            </div>
            <button className="btn btn-primary" disabled={title.trim().length < 3 || create.isPending} onClick={() => create.mutate()}>
              {create.isPending ? "Adding…" : "Add task"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
