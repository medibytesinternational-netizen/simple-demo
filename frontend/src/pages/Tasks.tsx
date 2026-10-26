import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post } from "../api";
import type { AppTask, Meta } from "../types";
import { useEvidence } from "../components/Evidence";
import { ReasonForm } from "../features/f15/ReasonForm";
import { canAcknowledge, escalationKind, isClosed } from "../features/f15/rules";
import type { ReasonTarget } from "../features/f15/types";
import { PageHeader } from "../components/PageHeader";
import { Banner, EmptyState, Field, ListRow, Menu, MenuItem, MetaChip, Panel, Pill, Progress, Skeleton, SummaryPanel, Tabs, Toolbar } from "../components/ui";
import type { Tone } from "../components/ui";
import { Icon } from "../components/icons";

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

  const [sort, setSort] = useState<SortKey>("due");
  const [composerOpen, setComposerOpen] = useState(false);
  const completedCount = all.filter((task) => task.status === "completed").length;
  const filterCounts: Record<(typeof FILTERS)[number], number> = {
    all: all.length,
    open: all.filter((task) => !["completed", "cancelled"].includes(task.status)).length,
    overdue,
    completed: all.filter((task) => ["completed", "cancelled"].includes(task.status)).length,
  };
  const nowMs = meta.data?.demo_now ? Date.parse(meta.data.demo_now) : null;
  const sorted = sortTasks(filtered, sort);

  return (
    <div className="pg-tasks">
      <PageHeader
        title="Tasks & escalations"
        description="Care tasks with an owner and a due time. Overdue work is flagged and can be escalated to a senior."
      />

      <SummaryPanel
        id="tasks"
        title="Task summary"
        items={[
          { label: "Active", value: accepted, note: "Accepted, acknowledged or in progress" },
          { label: "Overdue", value: overdue, tone: overdue ? "warning" : undefined, note: "Past due and still open" },
          { label: "Escalated", value: escalated, tone: escalated ? "critical" : undefined, note: "Level 1 or 2, with reason and time" },
          {
            label: "Completed",
            value: completedCount,
            tone: completedCount ? "success" : undefined,
            share: all.length ? completedCount / all.length : 0,
            note: all.length ? `${Math.round((completedCount / all.length) * 100)}% of ${all.length} tasks` : "No tasks yet",
          },
        ]}
      />

      {error ? <Banner tone="danger" role="alert">{error}</Banner> : null}
      {notice ? <Banner tone="success" role="status">{notice}</Banner> : null}

      <Toolbar bare label="Task list controls">
        <Tabs
          variant="segmented"
          label="Task status"
          value={filter}
          onSelect={(item) => setFilter(item)}
          items={FILTERS.map((item) => ({ key: item, label: FILTER_LABELS[item], count: filterCounts[item] }))}
        />
        <Menu label={`Sort: ${SORT_LABELS[sort]}`} icon="sort">
          {(close) => (
            <>
              <div className="menu-label">Sort tasks by</div>
              {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
                <MenuItem key={key} checked={sort === key} onSelect={() => { setSort(key); close(); }}>
                  {SORT_LABELS[key]}
                </MenuItem>
              ))}
            </>
          )}
        </Menu>
        <span className="toolbar-spacer" />
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => runEscalations.mutate()}
          disabled={runEscalations.isPending}
          aria-busy={runEscalations.isPending || undefined}
          title="Escalate tasks that are past due"
        >
          {runEscalations.isPending ? <span className="spinner" /> : <Icon name="refresh" size={15} />}
          {runEscalations.isPending ? "Checking…" : "Run escalation check"}
        </button>
        <button
          type="button"
          className="btn btn-ink btn-sm"
          aria-expanded={composerOpen}
          aria-controls="task-composer"
          onClick={() => setComposerOpen((open) => !open)}
        >
          <Icon name={composerOpen ? "close" : "plus"} size={15} />
          {composerOpen ? "Close" : "New task"}
        </button>
      </Toolbar>

      {composerOpen ? (
        <Panel
          id="task-composer"
          className="tk-composer"
          title="New task"
          sub="Tasks you add here start as accepted. Assign an owner from the list afterwards."
          actions={<Pill tone="ai">Creates as accepted</Pill>}
          padded
        >
          <div className="form-row">
            <div className="tk-grow">
              <Field label="Task" htmlFor="tk-title">
                <input id="tk-title" className="input" autoFocus value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Repeat potassium in 6 hours" />
              </Field>
            </div>
            <Field label="Priority" htmlFor="tk-priority">
              <select id="tk-priority" className="select" value={priority} onChange={(event) => setPriority(event.target.value)}>
                <option value="routine">routine</option>
                <option value="urgent">urgent</option>
                <option value="critical">critical</option>
              </select>
            </Field>
            <Field label="Due in hours" htmlFor="tk-due">
              <input id="tk-due" className="input tk-hours" type="number" min={1} value={dueHours} onChange={(event) => setDueHours(Number(event.target.value))} />
            </Field>
            <button
              type="button"
              className="btn btn-primary"
              disabled={title.trim().length < 3 || create.isPending}
              aria-busy={create.isPending || undefined}
              onClick={() => create.mutate()}
            >
              {create.isPending ? <span className="spinner" /> : null}
              {create.isPending ? "Adding…" : "Add task"}
            </button>
          </div>
        </Panel>
      ) : null}

      {tasks.isLoading ? <Skeleton variant="rows" count={4} /> : null}
      {!tasks.isLoading && !sorted.length ? (
        <EmptyState
          icon="tasks"
          title={filter === "all" ? "No tasks yet." : "No tasks in this filter."}
          action={!composerOpen ? <button type="button" className="btn btn-ink btn-sm" onClick={() => setComposerOpen(true)}><Icon name="plus" size={15} />New task</button> : undefined}
        >
          {filter === "all"
            ? "Tasks arrive when you accept them from a ward round draft. You can also add one by hand with New task."
            : "Try another status above, or add a task by hand with New task."}
        </EmptyState>
      ) : null}

      {sorted.length ? (
        <div className="rows tk-rows">
          {sorted.map((task) => {
            const step = LIFECYCLE.indexOf(task.status);
            const due = dueChip(task, nowMs);
            const kind = escalationKind(task);
            const busy = (update.isPending && update.variables?.id === task.id) || (acknowledge.isPending && acknowledge.variables === task.id);
            const primary =
              task.status === "proposed" ? (
                <button type="button" className="btn btn-sm btn-primary" aria-busy={busy || undefined} onClick={() => update.mutate({ id: task.id, status: "accepted" })}>
                  {busy ? <span className="spinner" /> : null}Accept
                </button>
              ) : task.status === "accepted" ? (
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  disabled={!canAcknowledge(task, userName)}
                  title={canAcknowledge(task, userName) ? "" : task.assigned_to ? `Only ${task.assigned_to} can acknowledge this task` : "Assign the task first"}
                  aria-busy={busy || undefined}
                  onClick={() => acknowledge.mutate(task.id)}
                >
                  {busy ? <span className="spinner" /> : null}Acknowledge
                </button>
              ) : task.status === "acknowledged" ? (
                <button type="button" className="btn btn-sm btn-primary" aria-busy={busy || undefined} onClick={() => update.mutate({ id: task.id, status: "in_progress" })}>
                  {busy ? <span className="spinner" /> : null}Start
                </button>
              ) : task.status === "in_progress" ? (
                <button type="button" className="btn btn-sm btn-primary" aria-busy={busy || undefined} onClick={() => update.mutate({ id: task.id, status: "completed" })}>
                  {busy ? <span className="spinner" /> : null}Complete
                </button>
              ) : null;
            return (
              <ListRow
                key={task.id}
                icon={task.status === "completed" ? "check" : task.escalation_level ? "alert" : "tasks"}
                tone={rowTone(task)}
                muted={isClosed(task)}
                title={task.title}
                meta={
                  <span className="tk-meta">
                    <span>{task.accepted_from_draft_id ? "Accepted from round draft" : task.source_event_id ? "From timeline" : "Added by hand"}</span>
                    {task.source_event_id ? (
                      <button type="button" className="link" onClick={() => showEvent(task.source_event_id!)}>
                        View source
                      </button>
                    ) : null}
                    {task.assigned_at ? <span>Assignment recorded</span> : null}
                    {task.acknowledged_at ? <span>Acknowledged by {task.acknowledged_by}</span> : null}
                  </span>
                }
                body={task.escalation_level && task.escalation_reason ? <span className="tk-reason">{task.escalation_reason}</span> : undefined}
                chips={
                  <>
                    <Pill tone={STATUS_TONE[statusBadge[task.status]] || "neutral"} dot>{task.status.replaceAll("_", " ")}</Pill>
                    <Pill tone={priorityTone(task.priority)}>{task.priority}</Pill>
                    <MetaChip icon="clock" tone={due.tone} title={due.title}>{due.text}</MetaChip>
                    {task.escalation_level ? (
                      <Pill tone="critical" icon="alert" title={task.escalation_reason || ""}>
                        L{task.escalation_level}{kind ? `, ${kind}` : ""}
                      </Pill>
                    ) : null}
                  </>
                }
                side={
                  <>
                    <div className="lrow-progress">
                      <Progress
                        steps={LIFECYCLE.length}
                        value={task.status === "completed" ? LIFECYCLE.length : Math.max(step, 0)}
                        current={step >= 0 && task.status !== "completed"}
                        label={task.status === "cancelled" ? "Cancelled" : `Step ${task.status === "completed" ? LIFECYCLE.length : step + 1} of ${LIFECYCLE.length}`}
                      />
                    </div>
                    <select
                      className="select select-sm tk-owner"
                      aria-label={`Owner of ${task.title}`}
                      value={task.assigned_to || task.owner || ""}
                      onChange={(event) => assign.mutate({ id: task.id, assigned_to: event.target.value })}
                    >
                      <option value="">Unassigned</option>
                      {ASSIGNEES.map((person) => <option key={person} value={person}>{person}</option>)}
                    </select>
                    {primary}
                    <Menu icon="more" ariaLabel={`More actions for ${task.title}`} buttonClass="icon-btn" align="right">
                      {(close) => (
                        <>
                          {task.status === "acknowledged" ? (
                            <MenuItem icon="check" onSelect={() => { close(); update.mutate({ id: task.id, status: "completed" }); }}>Complete</MenuItem>
                          ) : null}
                          {!isClosed(task) && (task.escalation_level || 0) < 2 ? (
                            <MenuItem icon="alert" onSelect={() => { close(); setReasonFor({ id: task.id, mode: "escalate" }); }}>Escalate</MenuItem>
                          ) : null}
                          {isClosed(task) ? (
                            <MenuItem icon="refresh" onSelect={() => { close(); setReasonFor({ id: task.id, mode: "reopen" }); }}>Reopen</MenuItem>
                          ) : null}
                          {!["completed", "cancelled"].includes(task.status) ? (
                            <MenuItem icon="close" danger onSelect={() => { close(); update.mutate({ id: task.id, status: "cancelled" }); }}>Cancel task</MenuItem>
                          ) : null}
                        </>
                      )}
                    </Menu>
                  </>
                }
                expand={reasonFor?.id === task.id ? (
                  <ReasonForm
                    mode={reasonFor.mode}
                    busy={escalate.isPending || reopen.isPending}
                    onCancel={() => setReasonFor(null)}
                    onConfirm={(reason) => (reasonFor.mode === "escalate" ? escalate : reopen).mutate({ id: task.id, reason })}
                  />
                ) : undefined}
              />
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

type SortKey = "due" | "priority";

const SORT_LABELS: Record<SortKey, string> = { due: "Due time", priority: "Priority" };

const FILTER_LABELS: Record<(typeof FILTERS)[number], string> = { all: "All", open: "Open", overdue: "Overdue", completed: "Completed" };

const LIFECYCLE = ["proposed", "accepted", "acknowledged", "in_progress", "completed"];

const STATUS_TONE: Record<string, Tone> = {
  "badge-neutral": "neutral",
  "badge-ai": "ai",
  "badge-warning": "warning",
  "badge-success": "success",
};

const PRIORITY_RANK: Record<string, number> = { critical: 0, urgent: 1, routine: 2 };

function priorityTone(priority: string): "critical" | "warning" | "neutral" {
  return priority === "critical" ? "critical" : priority === "urgent" ? "warning" : "neutral";
}

/** Tile tint: done is green, closed is plain, open work carries its priority. */
function rowTone(task: AppTask): "success" | "neutral" | "critical" | "warning" | "info" {
  if (task.status === "completed") return "success";
  if (isClosed(task)) return "neutral";
  const tone = priorityTone(task.priority);
  return tone === "neutral" ? "info" : tone;
}

function dueTime(task: AppTask) {
  return task.due_at ? Date.parse(task.due_at) : Number.POSITIVE_INFINITY;
}

/** Client-side ordering of the already-filtered list. */
function sortTasks(list: AppTask[], sort: SortKey) {
  return [...list].sort((a, b) => {
    if (sort === "priority") {
      const rank = (PRIORITY_RANK[a.priority] ?? 3) - (PRIORITY_RANK[b.priority] ?? 3);
      if (rank) return rank;
    }
    return dueTime(a) - dueTime(b);
  });
}

function span(ms: number) {
  const minutes = Math.round(ms / 60000);
  if (minutes < 60) return `${Math.max(minutes, 1)} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} d`;
}

/** "Due in 5 h" or "3 h overdue", measured against the demo clock. */
function dueChip(task: AppTask, nowMs: number | null): { text: string; title?: string; tone?: "critical" | "warning" } {
  if (!task.due_at) return { text: "No due time" };
  const at = new Date(task.due_at);
  const full = at.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  if (isClosed(task) || nowMs === null || Number.isNaN(at.getTime())) {
    return { text: `Due ${full}`, title: `Due ${full}`, tone: !isClosed(task) && task.is_overdue ? "warning" : undefined };
  }
  const diff = at.getTime() - nowMs;
  if (diff < 0) return { text: `${span(-diff)} overdue`, title: `Was due ${full}`, tone: "warning" };
  if (task.is_overdue) return { text: "Overdue", title: `Due ${full}`, tone: "warning" };
  return { text: `Due in ${span(diff)}`, title: `Due ${full}` };
}
