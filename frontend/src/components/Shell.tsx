import { useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, post, session } from "../api";
import type { AppState, Credits, Meta } from "../types";
import IntegrationBanner from "../features/s17/IntegrationBanner";
import { EvidenceDrawer } from "./Evidence";
import { Modal } from "./Modal";
import { Dock } from "./Dock";
import { PatientSearch } from "./PatientSearch";
import { initials } from "./PatientStrip";
import { ThemeToggle } from "./ThemeToggle";
import { findActive } from "./modules";
import { Icon } from "./icons";
import { DEMO_MODE, PREVIEW_LABEL } from "../demo/config";

// This file stays ASCII-only: a backend test reads it with the platform default encoding.
const SEP = String.fromCharCode(183);


// Documents still waiting for a person to confirm what OCR read.
const AWAITING_REVIEW = new Set(["needs_confirmation", "pending", "needs_manual_entry"]);

// One doctor and one browsable patient (Ravi). A browser that last ran when the app had roles or a
// patient picker may still hold those ids; drop them once at load so the first request is not refused.
session.setUser(null);
if (session.patient() !== "pat_ravi") session.setPatient(null);


export function Shell() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const tab = new URLSearchParams(location.search).get("tab");
  const [resetOpen, setResetOpen] = useState(false);

  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  const patientId = meta.data?.patient.id;
  const state = useQuery<AppState>({
    queryKey: ["state", patientId],
    queryFn: () => get<AppState>(`/patients/${patientId}/state`),
    enabled: !!patientId,
  });
  // Credits are not in the preview fixtures; the preview does not ask for them.
  const credits = useQuery<Credits>({ queryKey: ["credits"], queryFn: () => get<Credits>("/credits"), refetchInterval: 15000, enabled: !DEMO_MODE });

  // A patient the server refuses (a stale id) falls back to Ravi instead of leaving every page in error.
  useEffect(() => {
    if (meta.error instanceof ApiError && meta.error.status === 403 && session.patient()) {
      session.setPatient(null);
      queryClient.invalidateQueries();
    }
  }, [meta.error, queryClient]);

  const reset = useMutation({
    mutationFn: (mode: string) => post(`/demo/reset?mode=${mode}`),
    onSuccess: () => {
      queryClient.clear();
      setResetOpen(false);
      navigate("/dashboard");
    },
  });

  const active = findActive(location.pathname, tab);
  useEffect(() => {
    document.title = `${active?.label || "MediBytes"} ${SEP} MediBytes HMS`;
  }, [active?.label, location.pathname, location.search]);

  const openAlerts = state.data?.alerts.filter((alert) => alert.status === "open").length || 0;
  const overdue = state.data?.tasks.filter((t) => t.is_overdue && !["completed", "cancelled"].includes(t.status)).length || 0;
  const documents = state.data?.documents.filter((d) => AWAITING_REVIEW.has(d.ocr_status)).length || 0;
  const labs = state.data?.unreviewed_labs.length || 0;
  const counts = { alerts: openAlerts, overdue, documents, labs };
  const demoClock = meta.data?.demo_now
    ? new Date(meta.data.demo_now).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : null;
  const user = meta.data?.user?.name || meta.data?.demo_user || "Dr. Meera Shah";
  const role = meta.data?.demo_role || "Attending physician";

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">Skip to content</a>

      <div className="app-main">
        <header className="topbar glass">
          <Link to="/dashboard" className="topbar-brand" aria-label="MediBytes Hospital management, home">
            <span className="brand-mark" aria-hidden="true">MB</span>
            <span className="brand-text">
              <span className="brand-name">MediBytes</span>
              <span className="brand-sub">Hospital management</span>
            </span>
          </Link>
          <nav className="breadcrumbs" aria-label="Breadcrumb">
            <Link to="/dashboard">Home</Link>
            {active && active.id !== "dashboard" ? (
              <>
                <Icon name="chevron" size={14} />
                <span className="crumb-group">{active.group}</span>
                <Icon name="chevron" size={14} />
                <span aria-current="page" className="crumb-current">{active.label}</span>
              </>
            ) : (
              <>
                <Icon name="chevron" size={14} />
                <span aria-current="page" className="crumb-current">Dashboard</span>
              </>
            )}
          </nav>
          <PatientSearch />
          <div className="topbar-right">
            <button type="button" className="chrome-btn icon-only chrome-btn-search" onClick={() => navigate("/patients")} aria-label="Find a patient">
              <Icon name="search" size={17} />
            </button>
            {DEMO_MODE ? (
              <span className="env-pill" role="status" title={`${PREVIEW_LABEL}. All data is fictional. Nothing you do is saved.`}>
                <span className="env-dot" aria-hidden="true" /><span>Demo<span className="env-text-long"> preview</span></span>
              </span>
            ) : (
              <>
                <span className="env-pill" title="All data is fictional seed data.">
                  <span className="env-dot" aria-hidden="true" /><span>Synthetic<span className="env-text-long"> data</span></span>
                </span>
                <span className={`mode-pill ${meta.data?.llm_mode === "live" ? "live" : ""}`} title={meta.data?.live_available ? "OpenAI key detected" : "Drafts come from the cached demo set"}>
                  {meta.data?.llm_mode === "live" ? "Live drafts" : "Cached drafts"}
                </span>
                <IntegrationBanner />
              </>
            )}
            {demoClock ? (
              <span className="topbar-clock" title="Demo clock: the application's simulated time">
                <Icon name="clock" size={15} /> {demoClock}
              </span>
            ) : null}
            <ThemeToggle />
            <button type="button" className="chrome-btn" onClick={() => setResetOpen(true)} aria-label="Demo controls">
              <Icon name="refresh" size={16} /><span className="chrome-btn-label">Demo controls</span>
            </button>
            <span className="topbar-user" title={`${user} ${SEP} ${role}`}>
              <span className="avatar" aria-hidden="true">{initials(user)}</span>
              <span className="topbar-user-text">
                <span className="topbar-user-name">{user}</span>
                <span className="topbar-user-role">{role}</span>
              </span>
            </span>
          </div>
        </header>

        <main className="content-scroll" id="main-content" tabIndex={-1}>
          <div className="content">
            <Outlet />
          </div>
        </main>

        <Dock counts={counts} />
      </div>

      <EvidenceDrawer />

      {resetOpen ? (
        <Modal
          title="Demo controls"
          onClose={() => setResetOpen(false)}
          footer={<button className="btn" onClick={() => setResetOpen(false)}>Close</button>}
        >
          <p className="fs-13 muted" style={{ marginTop: 0 }}>
            {DEMO_MODE
              ? "Demo reset is not available in the UI preview: there is no backend. Refresh the page to clear anything added in this tab."
              : "Reset the synthetic patient. All drafts, tasks, alerts, documents and audit entries are replaced."}
          </p>
          {!DEMO_MODE ? (
            <p className="small muted" style={{ marginTop: 0 }}>
              Draft mode: {meta.data?.llm_mode === "live" ? "live model" : "cached demo drafts"}.
              {credits.data ? ` ${credits.data.balance.toLocaleString()} of ${credits.data.pack_size.toLocaleString()} credits remaining.` : ""}
            </p>
          ) : null}
          <div className="grid-2 mt-3">
            <button className="choice-card" onClick={() => reset.mutate("start")} disabled={reset.isPending || DEMO_MODE}>
              <span className="card-title">Fresh start</span>
              <span className="small muted mt-1">Demographics and allergy only. Empty timeline.</span>
            </button>
            <button className="choice-card" onClick={() => reset.mutate("rehearsal")} disabled={reset.isPending || DEMO_MODE}>
              <span className="card-title">Rehearsal data</span>
              <span className="small muted mt-1">Pre-seeded admission, labs, medicines, tasks, alerts, bill and outside scan.</span>
            </button>
          </div>
          {reset.isPending ? <div className="banner mt-3" role="status"><span className="spinner" /> Resetting the demo data...</div> : null}
          {reset.isError ? <div className="error-box mt-3" role="alert">The demo data was not reset: {(reset.error as Error).message}</div> : null}
        </Modal>
      ) : null}
    </div>
  );
}
