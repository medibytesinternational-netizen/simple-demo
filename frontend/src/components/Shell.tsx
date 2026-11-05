import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, post, session } from "../api";
import type { AppState, Credits, Meta } from "../types";
import { EvidenceDrawer } from "./Evidence";
import { Modal } from "./Modal";
import { FooterBar, MenuBar, StatusBar } from "./legacy/HisChrome";
import { findActive } from "./modules";
import { DEMO_MODE, PREVIEW_LABEL } from "../demo/config";

// This file stays ASCII-only: a backend test reads it with the platform default encoding.
const SEP = String.fromCharCode(183);


// Documents still waiting for a person to confirm what OCR read.
const AWAITING_REVIEW = new Set(["needs_confirmation", "pending", "needs_manual_entry"]);

// One doctor and one browsable patient (Ravi). A browser that last ran when the app had roles or a
// patient picker may still hold those ids; drop them once at load so the first request is not refused.
// Known staff accounts: the chief doctor, a senior doctor and a nurse. Anything else is stale.
if (!["u_meera", "u_arjun", "u_anita"].includes(session.user() || "u_meera")) session.setUser(null);
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
  const user = meta.data?.user?.name || meta.data?.demo_user || "Dr. Meera Shah";
  const hospital = "MediBytes Hospital";

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">Skip to content</a>

      <div className="app-main">
        <StatusBar
          loginId={(meta.data?.user as { id?: string } | undefined)?.id?.replace(/\D/g, "") || "22149"}
          user={user}
          hospital={hospital}
          screen={active?.label || "Dashboard"}
          onControls={() => setResetOpen(true)}
          userId={meta.data?.user?.id || "u_meera"}
          onSwitchUser={(id) => {
            session.setUser(id === "u_meera" ? null : id);
            queryClient.clear();
          }}
        />
        <MenuBar
          counts={counts}
          patient={meta.data ? {
            name: meta.data.patient.name,
            mrn: meta.data.patient.mrn,
            age: meta.data.patient.age,
            sex: meta.data.patient.sex,
            place: [meta.data.encounter?.ward, meta.data.encounter?.bed].filter(Boolean).join(" / "),
            allergies: meta.data.patient.allergies || [],
          } : null}
        />

        <main className="content-scroll" id="main-content" tabIndex={-1}>
          <div className="content">
            <Outlet />
          </div>
        </main>

        <FooterBar hospital={hospital} status={DEMO_MODE ? PREVIEW_LABEL : `${openAlerts} open alerts ${SEP} ${overdue} overdue tasks`} />
      </div>

      <EvidenceDrawer />

      {resetOpen ? (
        <Modal
          title="Workspace controls"
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
          {reset.isPending ? <div className="banner mt-3" role="status"><span className="spinner" /> Resetting the patient workspace...</div> : null}
          {reset.isError ? <div className="error-box mt-3" role="alert">The patient workspace was not reset: {(reset.error as Error).message}</div> : null}
        </Modal>
      ) : null}
    </div>
  );
}
