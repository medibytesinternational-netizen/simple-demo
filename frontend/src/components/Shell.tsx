import { useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../api";
import type { AppState, AuditEntry, Meta } from "../types";
import { EvidenceDrawer } from "./Evidence";
import { Modal } from "./Modal";
import { Launcher } from "./Launcher";
import { FlowFooter, SideNav } from "./SideNav";
import { DEMO_MODE, PREVIEW_LABEL } from "../demo/config";

// "The patient header never changes, so a client who clicks away stays oriented."
// It is shown on every screen of the demo path. Patient List and New admission work
// across patients, so the primary patient's header would be misleading there.
const NO_PATIENT_HEADER = new Set(["/patients", "/admission"]);

function initials(name: string) {
  const parts = name.replace(/^(dr|mr|mrs|ms|prof)\.?\s+/i, "").split(" ").filter(Boolean);
  return parts.map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

export function Shell() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const [resetOpen, setResetOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [launcherOpen, setLauncherOpen] = useState(false);

  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  const state = useQuery<AppState>({ queryKey: ["state"], queryFn: () => get<AppState>("/patients/pat_ravi/state") });
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
  const demoClock = meta.data?.demo_now
    ? new Date(meta.data.demo_now)
        .toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
        .replace(",", " ·")
    : "—";
  const showPatient = !NO_PATIENT_HEADER.has(location.pathname);
  const egfr = state.data?.latest_labs.find((lab) => lab.name.toLowerCase() === "egfr");
  const stayDay = meta.data?.encounter.admitted_at && meta.data.demo_now
    ? Math.floor((Date.parse(meta.data.demo_now.slice(0, 10)) - Date.parse(meta.data.encounter.admitted_at.slice(0, 10))) / 86_400_000) + 1
    : null;
  const user = meta.data?.demo_user || "Dr. Meera Shah";

  return (
    <div className="app-shell">
      <header className="header">
        <div className="brand">
          <div className="brand-mark">MB</div>
          <div>
            <div className="brand-name">MediBytes HMS</div>
            <div className="brand-sub">Demo hospital</div>
          </div>
        </div>
        <div className="header-divider" aria-hidden="true" />
        <div className="hospital-name">
          <div className="hospital-title">MediBytes Demo Hospital</div>
          <div className="brand-sub">Hospital management system</div>
        </div>
        <div className="header-actions">
          <span className="demo-clock">DEMO {demoClock}</span>
          {DEMO_MODE ? (
            <span className="preview-pill" role="status">{PREVIEW_LABEL}</span>
          ) : (
            <>
              <span
                className={`mode-badge ${meta.data?.llm_mode === "live" ? "live" : ""}`}
                title={meta.data?.live_available ? "OpenAI key detected" : "Add OPENAI_API_KEY to switch to live GPT-4o"}
              >
                {meta.data?.llm_mode === "live" ? "Live GPT-4o" : "Cached demo"}
              </span>
              <span className="synthetic-badge">Synthetic data</span>
            </>
          )}
          <span className="header-user">
            <span className="avatar">{initials(user)}</span>
            <span className="header-user-text">
              <span className="header-user-name">{user}</span>
              <span className="header-user-role">{meta.data?.demo_role || "Attending"}</span>
            </span>
          </span>
          <button className="btn btn-header" onClick={() => setAuditOpen(true)}>Audit</button>
          <button className="btn btn-header-solid" onClick={() => setResetOpen(true)}>Demo</button>
        </div>
      </header>


      <div className="shell-body">
        <SideNav counts={{ alerts: openAlerts }} onAudit={() => setAuditOpen(true)} onLauncher={() => setLauncherOpen(true)} />
        <div className="shell-main">
          {showPatient ? (
            <div className="patient-bar" role="region" aria-label="Current patient">
              {meta.data ? (
                <>
                  <span className="avatar avatar-soft">{initials(meta.data.patient.name)}</span>
                  <div className="patient-id">
                    <div className="patient-name">{meta.data.patient.name}</div>
                    <div className="patient-meta">{meta.data.patient.age} y · {meta.data.patient.sex} · MRN {meta.data.patient.mrn}</div>
                  </div>
                  <div className="patient-field"><span>Location</span>{meta.data.encounter.ward} · {meta.data.encounter.bed}{stayDay && meta.data.encounter.status === "active" ? ` · day ${stayDay}` : ""}</div>
                  <div className="patient-field"><span>Attending</span>{meta.data.encounter.attending}</div>
                  {egfr ? (
                    <div className="patient-field"><span>Latest eGFR</span><strong className={`egfr-value ${egfr.flag === "low" || egfr.flag === "high" ? "lab-flag" : ""}`}>{egfr.value}{egfr.flag ? ` · ${egfr.flag}` : ""}</strong></div>
                  ) : null}
                  <span className="allergy-flag">⚠ Allergy: {meta.data.patient.allergies.join(", ") || "none recorded"}</span>
                  {openAlerts ? <a className="alert-count" href="/safety?tab=alerts" onClick={(e) => { e.preventDefault(); navigate("/safety?tab=alerts"); }}>{openAlerts} open alert{openAlerts === 1 ? "" : "s"}</a> : null}
                  <span className={meta.data.encounter.status === "discharged" ? "badge badge-success" : "badge badge-neutral"}>
                    {meta.data.encounter.status}
                  </span>
                </>
              ) : (
                <span className="loading">Loading patient…</span>
              )}
            </div>
          ) : null}
          <main className="content-scroll" id="main-content">
            <div className="content">
              <Outlet />
              <FlowFooter />
            </div>
          </main>
        </div>
      </div>

      {launcherOpen ? <Launcher onClose={() => setLauncherOpen(false)} onAudit={() => setAuditOpen(true)} /> : null}

      <EvidenceDrawer />

      {resetOpen ? (
        <Modal
          title="Demo controls"
          onClose={() => setResetOpen(false)}
          footer={<button className="btn" onClick={() => setResetOpen(false)}>Cancel</button>}
        >
          <p className="fs-13 muted" style={{ marginTop: 0 }}>
            {DEMO_MODE
              ? "Demo reset is not available in the UI preview: there is no backend. Refresh the page to clear anything added in this tab."
              : "Reset the synthetic patient. All drafts, tasks, alerts, documents and audit entries are replaced."}
          </p>
          <div className="grid-2 mt-3">
            <button className="card card-pad" style={{ textAlign: "left" }} onClick={() => reset.mutate("start")} disabled={reset.isPending || DEMO_MODE}>
              <div className="card-title">Fresh start</div>
              <div className="small muted mt-1">Demographics and allergy only. Empty timeline. Walk the ten-minute script from the beginning.</div>
            </button>
            <button className="card card-pad" style={{ textAlign: "left" }} onClick={() => reset.mutate("rehearsal")} disabled={reset.isPending || DEMO_MODE}>
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
          <aside className="drawer" style={{ width: "min(520px, 94vw)" }} aria-label="Audit log">
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
