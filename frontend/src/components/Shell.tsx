import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, post, session } from "../api";
import type { AppState, AuditEntry, Credits, Meta } from "../types";
import { EvidenceDrawer } from "./Evidence";
import { Modal } from "./Modal";
import IntegrationBanner from "../features/s17/IntegrationBanner";

const NAV = [
  { path: "/timeline", label: "Timeline", icon: "TL" },
  { path: "/notes", label: "Notes", icon: "NT" },
  { path: "/safety", label: "Safety", icon: "SF" },
  { path: "/tasks", label: "Tasks", icon: "TK" },
  { path: "/documents", label: "Documents", icon: "DC" },
  { path: "/discharge", label: "Discharge", icon: "DS" },
  { path: "/revenue", label: "Revenue", icon: "RV" },
  { path: "/dashboard", label: "Dashboard", icon: "DB" },
];

// One doctor and one browsable patient (Ravi). A browser that last ran when the app had roles or a
// patient picker may still hold those ids; drop them once at load so the first request is not refused.
session.setUser(null);
if (session.patient() !== "pat_ravi") session.setPatient(null);

export function Shell() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [resetOpen, setResetOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);

  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  const patientId = meta.data?.patient.id;
  const state = useQuery<AppState>({
    queryKey: ["state", patientId],
    queryFn: () => get<AppState>(`/patients/${patientId}/state`),
    enabled: !!patientId,
  });
  const credits = useQuery<Credits>({ queryKey: ["credits"], queryFn: () => get<Credits>("/credits"), refetchInterval: 15000 });

  // A patient the server refuses (a stale id) falls back to Ravi instead of leaving every page in error.
  useEffect(() => {
    if (meta.error instanceof ApiError && meta.error.status === 403 && session.patient()) {
      session.setPatient(null);
      queryClient.invalidateQueries();
    }
  }, [meta.error, queryClient]);

  const audit = useQuery<{ audit: AuditEntry[] }>({
    queryKey: ["audit", "shell"],
    queryFn: () => get<{ audit: AuditEntry[] }>("/audit?limit=80"),
    enabled: auditOpen,
  });

  const reset = useMutation({
    mutationFn: (mode: string) => post(`/demo/reset?mode=${mode}`),
    onSuccess: () => {
      queryClient.clear();
      setResetOpen(false);
      navigate("/timeline");
    },
  });

  const openAlerts = state.data?.alerts.filter((alert) => alert.status === "open").length || 0;
  const overdue = state.data?.tasks.filter((task) => task.is_overdue).length || 0;
  const pendingDocs = state.data?.documents.filter((document) => document.ocr_status !== "confirmed" && document.ocr_status !== "reviewed").length || 0;
  const demoClock = meta.data?.demo_now
    ? new Date(meta.data.demo_now)
        .toLocaleString("en-GB", {
          day: "2-digit",
          month: "short",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })
        .replace(",", " ·")
    : "—";

  const counts: Record<string, { value: number; kind: string }> = {
    "/safety": { value: openAlerts, kind: "critical" },
    "/tasks": { value: overdue, kind: "warning" },
    "/documents": { value: pendingDocs, kind: "warning" },
  };

  return (
    <div className="app-shell">
      <header className="header">
        <div className="brand">
          <div className="brand-mark">MB</div>
          <div>
            <div className="brand-name">MediBytes ARD</div>
            <div className="brand-sub">Clinical demo console</div>
          </div>
        </div>
        {meta.data ? (
          <div className="patient-header">
            <div>
              <div className="patient-name">
                {meta.data.patient.name}
                <span className="patient-meta"> · {meta.data.patient.age}{meta.data.patient.sex.charAt(0)} · {meta.data.patient.mrn}</span>
              </div>
              <div className="patient-meta">
                {meta.data.encounter.kind} · {meta.data.encounter.ward} · {meta.data.encounter.bed} · {meta.data.encounter.attending}
              </div>
            </div>
            <span className="allergy-flag">Allergy: {meta.data.patient.allergies.join(", ") || "none"}</span>
            <span className={meta.data.encounter.status === "discharged" ? "badge badge-success" : "badge badge-neutral"}>
              {meta.data.encounter.status}
            </span>
          </div>
        ) : (
          <div className="patient-header"><span className="loading">Loading patient…</span></div>
        )}
        <div className="header-actions">
          <span className={`mode-badge ${meta.data?.llm_mode === "live" ? "live" : ""}`} title={meta.data?.live_available ? "OpenAI key detected" : "Add OPENAI_API_KEY to switch to live GPT-4o"}>
            {meta.data?.llm_mode === "live" ? "Live GPT-4o" : "Cached demo"}
          </span>
          <span className="badge badge-neutral" title={`Pack of ${credits.data?.pack_size ?? "—"} credits. Reading a report 1, voice note 2, medicine reconciliation 2, report analysis 4, discharge summary 5.`}>
            {credits.data ? `${credits.data.balance.toLocaleString()} credits` : "— credits"}
          </span>
          <span className="demo-clock">DEMO {demoClock}</span>
          <button className="btn btn-sm" onClick={() => setAuditOpen(true)}>Audit</button>
          <button className="btn btn-sm" onClick={() => setResetOpen(true)}>Demo</button>
        </div>
      </header>

      <div className="body-grid">
        <nav className="left-nav">
          <div className="nav-section-label">Workspace</div>
          {NAV.map((item) => {
            const count = counts[item.path];
            return (
              <NavLink key={item.path} to={item.path} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
                <span className="nav-icon">{item.icon}</span>
                <span>{item.label}</span>
                {count?.value ? <span className={`nav-count ${count.kind}`}>{count.value}</span> : null}
              </NavLink>
            );
          })}
          <div className="nav-footer">
            <div><strong>Synthetic data only.</strong></div>
            <div className="mt-1">Rules first. GPT writes the sentence. A human commits.</div>
            <div className="mt-2 mono">{meta.data?.user.name}</div>
            <div>{meta.data?.user.role}</div>
          </div>
        </nav>

        <main className="content">
          <div className="mb-3"><IntegrationBanner /></div>
          <Outlet />
        </main>
      </div>

      <EvidenceDrawer />

      {resetOpen ? (
        <Modal
          title="Demo controls"
          onClose={() => setResetOpen(false)}
          footer={<button className="btn" onClick={() => setResetOpen(false)}>Cancel</button>}
        >
          <p className="fs-13 muted" style={{ marginTop: 0 }}>
            Reset the synthetic patient. All drafts, tasks, alerts, documents and audit entries are replaced.
          </p>
          <div className="grid-2 mt-3">
            <button className="card card-pad" style={{ textAlign: "left" }} onClick={() => reset.mutate("start")} disabled={reset.isPending}>
              <div className="card-title">Fresh start</div>
              <div className="small muted mt-1">Demographics and allergy only. Empty timeline. Walk the ten-minute script from the beginning.</div>
            </button>
            <button className="card card-pad" style={{ textAlign: "left" }} onClick={() => reset.mutate("rehearsal")} disabled={reset.isPending}>
              <div className="card-title">Rehearsal data</div>
              <div className="small muted mt-1">Pre-seeded admission, labs, meds, tasks, alerts, bill and outside scan. Ready to demo every screen.</div>
            </button>
          </div>
          {reset.isPending ? <div className="banner mt-3"><span className="spinner" /> Resetting…</div> : null}
        </Modal>
      ) : null}

      {auditOpen ? (
        <>
          <div className="drawer-backdrop" onClick={() => setAuditOpen(false)} />
          <aside className="drawer" style={{ width: "min(520px, 94vw)" }}>
            <div className="drawer-head">
              <div>
                <div className="card-title">Audit log</div>
                <div className="small muted">Every write and every model call</div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setAuditOpen(false)}>Close</button>
            </div>
            <div className="drawer-body">
              {audit.isLoading ? <div className="loading">Loading audit…</div> : null}
              {audit.data?.audit.map((entry) => (
                <div className="list-row" key={entry.id} style={{ display: "block" }}>
                  <div className="flex items-center justify-between gap-2">
                    <span className={`badge ${entry.actor_type === "model" ? "badge-ai" : entry.actor_type === "system" ? "badge-neutral" : "badge-success"}`}>
                      {entry.action.replaceAll("_", " ")}
                    </span>
                    <span className="small muted mono">{new Date(entry.created_at).toLocaleTimeString()}</span>
                  </div>
                  <div className="fs-13 mt-1"><strong>{entry.actor_name}</strong> · {entry.entity_type} <span className="mono small">{entry.entity_id}</span></div>
                  {entry.after && Object.keys(entry.after).length ? (
                    <div className="small muted mt-1" style={{ wordBreak: "break-word" }}>
                      {Object.entries(entry.after).slice(0, 4).map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : value}`).join(" · ")}
                    </div>
                  ) : null}
                </div>
              ))}
              {audit.data && !audit.data.audit.length ? <div className="empty">No audit entries yet.</div> : null}
            </div>
          </aside>
        </>
      ) : null}
    </div>
  );
}
