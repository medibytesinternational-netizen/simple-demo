import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, post, session } from "../api";
import type { AppState, Credits, Meta } from "../types";
import { EvidenceDrawer } from "./Evidence";
import { Modal } from "./Modal";
import { Launchpad } from "./Launchpad";
import { NotForRole, PatientBar, Sidebar, TopBar } from "./Chrome";
import { findActive, isPatientRoute } from "./modules";
import { DEFAULT_STAFF_ID, ROLES, STAFF, canSee, currentRole, staffById } from "./roles";
import { DEMO_MODE, PREVIEW_LABEL } from "../demo/config";

// This file stays ASCII-only: a backend test reads it with the platform default encoding.
const SEP = String.fromCharCode(183);
const COLLAPSE_KEY = "mb.nav.collapsed";

// Documents still waiting for a person to confirm what OCR read.
const AWAITING_REVIEW = new Set(["needs_confirmation", "pending", "needs_manual_entry"]);

// A browser that last ran with an older staff list may hold a user id that no longer exists; drop it
// once at load. A stale patient id is handled below: the server refuses it and the shell falls back.
if (!STAFF.some((s) => s.id === (session.user() || DEFAULT_STAFF_ID))) session.setUser(null);

function readCollapsed() {
  try { return window.localStorage.getItem(COLLAPSE_KEY) === "1"; } catch { return false; }
}
const isNarrow = () => window.matchMedia("(max-width: 900px)").matches;

export function Shell() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const tab = new URLSearchParams(location.search).get("tab");
  const [resetOpen, setResetOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [role, setRole] = useState(currentRole);

  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  const patientId = meta.data?.patient.id;
  const state = useQuery<AppState>({
    queryKey: ["state", patientId],
    queryFn: () => get<AppState>(`/patients/${patientId}/state`),
    enabled: !!patientId,
  });
  // Credits are not in the preview fixtures; the preview does not ask for them.
  const credits = useQuery<Credits>({ queryKey: ["credits"], queryFn: () => get<Credits>("/credits"), refetchInterval: 15000, enabled: !DEMO_MODE });

  // A patient the server refuses (a stale or removed id) falls back to the default patient instead of
  // leaving every page in error.
  useEffect(() => {
    if (meta.error instanceof ApiError && meta.error.status === 403 && session.patient()) {
      session.setPatient(null);
      queryClient.invalidateQueries();
    }
  }, [meta.error, queryClient]);

  // Ctrl+K / Cmd+K opens search from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // A page change closes the phone navigation drawer.
  useEffect(() => setNavOpen(false), [location.pathname, location.search]);

  const reset = useMutation({
    mutationFn: (mode: string) => post(`/demo/reset?mode=${mode}`),
    onSuccess: () => {
      queryClient.clear();
      setResetOpen(false);
      navigate(ROLES[role].home);
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
  const inPatient = isPatientRoute(location.pathname);
  const allowed = !active || canSee(role, active.id);
  const userId = session.user() || DEFAULT_STAFF_ID;

  const toggleNav = () => {
    if (isNarrow()) { setNavOpen((v) => !v); return; }
    setCollapsed((v) => {
      try { window.localStorage.setItem(COLLAPSE_KEY, v ? "0" : "1"); } catch { /* storage blocked */ }
      return !v;
    });
  };

  return (
    <div className="app hx-app">
      <a className="skip-link" href="#main-content">Skip to content</a>

      <TopBar
        role={role}
        userId={userId}
        counts={counts}
        preview={DEMO_MODE ? PREVIEW_LABEL : undefined}
        onMenu={toggleNav}
        onSearch={() => setSearchOpen(true)}
        onControls={() => setResetOpen(true)}
        onSwitchUser={(id) => {
          const next = staffById(id);
          session.setUser(next.id === DEFAULT_STAFF_ID ? null : next.id);
          setRole(next.app);
          queryClient.clear();
          navigate(ROLES[next.app].home);
        }}
      />

      <div className={`hx-body${collapsed ? " nav-collapsed" : ""}`}>
        <Sidebar
          role={role}
          counts={counts}
          patientName={meta.data?.patient.name}
          inPatient={inPatient}
          open={navOpen}
          collapsed={collapsed}
          onClose={() => setNavOpen(false)}
          onToggleCollapsed={toggleNav}
        />

        <div className="app-main">
          {inPatient && meta.data ? (
            <PatientBar patient={{
              name: meta.data.patient.name,
              mrn: meta.data.patient.mrn,
              age: meta.data.patient.age,
              sex: meta.data.patient.sex,
              place: [meta.data.encounter?.ward, meta.data.encounter?.bed].filter(Boolean).join(" / "),
              allergies: meta.data.patient.allergies || [],
            }} />
          ) : null}

          <main className="content-scroll" id="main-content" tabIndex={-1}>
            <div className="content">
              {allowed ? <Outlet /> : <NotForRole role={role} page={active!.label} />}
            </div>
          </main>
        </div>
      </div>

      {searchOpen ? <Launchpad role={role} counts={counts} onClose={() => setSearchOpen(false)} /> : null}
      <EvidenceDrawer />

      {resetOpen ? (
        <Modal
          title="Workspace"
          onClose={() => setResetOpen(false)}
          footer={<button className="btn" onClick={() => setResetOpen(false)}>Close</button>}
        >
          <p className="fs-13 muted" style={{ marginTop: 0 }}>
            {DEMO_MODE
              ? "Workspace reset is not available in the preview environment. Refresh the page to clear anything added in this tab."
              : "Reset the patient workspace. All reports, tasks, alerts, documents and audit entries are replaced."}
          </p>
          {!DEMO_MODE ? (
            <p className="small muted" style={{ marginTop: 0 }}>
              Analysis mode: {meta.data?.llm_mode === "live" ? "MediBytes Analysis" : "saved reports"}.
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
              <span className="small muted mt-1">Existing admission, labs, medicines, tasks, alerts, bill and outside scan.</span>
            </button>
          </div>
          <div className="button-row mt-3">
            <button className="btn" onClick={() => {
              if (document.fullscreenElement) void document.exitFullscreen();
              else void document.documentElement.requestFullscreen?.();
            }}>Toggle full screen</button>
          </div>
          {reset.isPending ? <div className="banner mt-3" role="status"><span className="spinner" /> Resetting the patient workspace...</div> : null}
          {reset.isError ? <div className="error-box mt-3" role="alert">The patient workspace was not reset: {(reset.error as Error).message}</div> : null}
        </Modal>
      ) : null}
    </div>
  );
}
