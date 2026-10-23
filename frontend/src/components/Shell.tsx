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
import { findActive } from "./modules";
import { Icon } from "./icons";
import { DEMO_MODE, PREVIEW_LABEL } from "../demo/config";

// The clinical modules are scoped to the primary patient's encounter, so the
// identity banner appears on exactly those screens and nowhere else.
const PATIENT_SCOPED = new Set(["/timeline", "/notes", "/safety", "/documents", "/discharge", "/revenue", "/tasks"]);

function initials(name: string) {
  const parts = name.replace(/^(dr|mr|mrs|ms|prof)\.?\s+/i, "").split(" ").filter(Boolean);
  return parts.map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

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
    document.title = `${active?.label || "MediBytes"} · MediBytes HMS`;
  }, [active?.label, location.pathname, location.search]);

  const openAlerts = state.data?.alerts.filter((alert) => alert.status === "open").length || 0;
  const overdue = state.data?.tasks.filter((t) => t.is_overdue && !["completed", "cancelled"].includes(t.status)).length || 0;
  const counts = { alerts: openAlerts, overdue };
  const demoClock = meta.data?.demo_now
    ? new Date(meta.data.demo_now).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : "—";
  const user = meta.data?.user?.name || meta.data?.demo_user || "Dr. Meera Shah";
  const showPatient = PATIENT_SCOPED.has(location.pathname);
  const egfr = state.data?.latest_labs.find((lab) => lab.name.toLowerCase() === "egfr");
  const stayDay = meta.data?.encounter.admitted_at && meta.data.demo_now
    ? Math.floor((Date.parse(meta.data.demo_now.slice(0, 10)) - Date.parse(meta.data.encounter.admitted_at.slice(0, 10))) / 86_400_000) + 1
    : null;

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">Skip to content</a>

      <div className="app-main">
        <header className="topbar">
          {/* All modules open from the dock's Modules button; the brand sits here now that there is no left navigation. */}
          <Link to="/dashboard" className="sidenav-brand topbar-brand" aria-label="MediBytes — Hospital management, home">
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
                <span>{active.group}</span>
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
            {DEMO_MODE ? (
              <span className="env-pill" role="status" title="All data is fictional. Nothing you do is saved.">
                <span className="env-dot" aria-hidden="true" />{PREVIEW_LABEL}
              </span>
            ) : (
              <>
                <span className="env-pill" title="All data is fictional seed data.">
                  <span className="env-dot" aria-hidden="true" />Synthetic data
                </span>
                <span className={`mode-pill ${meta.data?.llm_mode === "live" ? "live" : ""}`} title={meta.data?.live_available ? "OpenAI key detected" : "Drafts come from the cached demo set"}>
                  {meta.data?.llm_mode === "live" ? "Live drafts" : "Cached drafts"}
                </span>
                <span className="mode-pill" title={`Pack of ${credits.data?.pack_size ?? "—"} credits. Reading a report 1, voice note 2, medicine reconciliation 2, report analysis 4, discharge summary 5.`}>
                  {credits.data ? `${credits.data.balance.toLocaleString()} credits` : "— credits"}
                </span>
              </>
            )}
            <span className="topbar-clock" title="Demo clock — the application's simulated time">
              <Icon name="clock" size={15} /> {demoClock}
            </span>
            <button type="button" className="btn btn-sm" onClick={() => setResetOpen(true)}>Demo controls</button>
            <span className="topbar-user" title={`${user} · ${meta.data?.demo_role || "Attending physician"}`}>
              <span className="avatar">{initials(user)}</span>
              <span className="topbar-user-text">
                <span className="topbar-user-name">{user}</span>
                <span className="topbar-user-role">{meta.data?.demo_role || "Attending physician"}</span>
              </span>
            </span>
          </div>
        </header>

        {showPatient ? (
          <section className="patient-banner" aria-label="Current patient">
            {meta.data ? (
              <>
                <span className="avatar avatar-lg">{initials(meta.data.patient.name)}</span>
                <div className="pb-identity">
                  <div className="pb-name">
                    {meta.data.patient.name}
                    <span className="pb-record-tag" title="This patient has a full clinical record in the demo data">Full record</span>
                  </div>
                  <div className="pb-meta">{meta.data.patient.age} y · {meta.data.patient.sex} · MRN {meta.data.patient.mrn}</div>
                </div>
                <dl className="pb-facts">
                  <div><dt>Location</dt><dd>{meta.data.encounter.ward} · {meta.data.encounter.bed}</dd></div>
                  <div><dt>Stay</dt><dd>{meta.data.encounter.kind}{stayDay && meta.data.encounter.status === "active" ? ` · day ${stayDay}` : ` · ${meta.data.encounter.status}`}</dd></div>
                  <div><dt>Attending</dt><dd>{meta.data.encounter.attending}</dd></div>
                  {egfr ? <div><dt>Latest eGFR</dt><dd className={egfr.flag === "low" || egfr.flag === "high" ? "pb-flag" : ""}>{egfr.value}{egfr.flag ? ` · ${egfr.flag}` : ""}</dd></div> : null}
                </dl>
                <div className="pb-status">
                  <span className="pb-allergy"><Icon name="alert" size={15} /> Allergy: {meta.data.patient.allergies.join(", ") || "none recorded"}</span>
                  {openAlerts ? <Link className="pb-alerts" to="/safety?tab=alerts">{openAlerts} open alert{openAlerts === 1 ? "" : "s"}</Link> : null}
                </div>
              </>
            ) : <span className="muted">Loading patient…</span>}
          </section>
        ) : null}

        <main className="content-scroll" id="main-content" tabIndex={-1}>
          <div className="content">
            {DEMO_MODE ? null : <div className="mb-3"><IntegrationBanner /></div>}
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
          {reset.isPending ? <div className="banner mt-3"><span className="spinner" /> Resetting…</div> : null}
          {reset.isError ? <div className="error-box mt-3" role="alert">The demo data was not reset: {(reset.error as Error).message}</div> : null}
        </Modal>
      ) : null}
    </div>
  );
}
