import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { get, post } from "../api";
import type { Draft, Reconciliation } from "../types";
import { DismissFields, dismissReady } from "../features/f05/DismissFields";
import { CATEGORY_LABEL } from "../features/f05/types";
import type { AlertRow, DismissCategory } from "../features/f05/types";
import ReconciliationQueue from "../features/f06/ReconciliationQueue";
import MedicineOrders from "../features/f06/MedicineOrders";
import { DraftReview } from "../components/DraftReview";
import { EvidenceChip } from "../components/Evidence";
import { Modal } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";

export function SafetyPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "meds" ? "meds" : "alerts";
  const queryClient = useQueryClient();
  const [dismissing, setDismissing] = useState<AlertRow | null>(null);
  const [reason, setReason] = useState("");
  const [category, setCategory] = useState<DismissCategory | "">("");
  const [error, setError] = useState("");

  const alerts = useQuery<{ alerts: AlertRow[]; open_count: number }>({
    queryKey: ["alerts"],
    queryFn: () => get("/alerts"),
  });
  const reconciliation = useQuery<Reconciliation>({
    queryKey: ["reconciliation"],
    queryFn: () => get("/medications/reconciliation"),
    enabled: tab === "meds",
  });
  const reconDrafts = useQuery<{ drafts: Draft[] }>({
    queryKey: ["drafts", "F6"],
    queryFn: () => get("/drafts?feature=F6&limit=1"),
    enabled: tab === "meds",
  });

  const acknowledge = useMutation({
    mutationFn: (id: string) => post(`/alerts/${id}/acknowledge`),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const dismiss = useMutation({
    mutationFn: ({ id, reason, category }: { id: string; reason: string; category: DismissCategory }) =>
      post(`/alerts/${id}/dismiss`, { reason, category }),
    onSuccess: () => {
      setDismissing(null);
      setReason("");
      setCategory("");
      setError("");
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const evaluate = useMutation({
    mutationFn: () => post("/alerts/evaluate"),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const explain = useMutation({
    mutationFn: () => post<any>("/medications/reconciliation/generate"),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const open = alerts.data?.alerts.filter((alert) => alert.status === "open") || [];
  const closed = alerts.data?.alerts.filter((alert) => alert.status !== "open") || [];
  const latestRecon = reconDrafts.data?.drafts?.[0];

  return (
    <>
      <PageHeader
        title={tab === "meds" ? "Medication reconciliation" : "Clinical alerts"}
        description={tab === "meds"
          ? "Medicines the patient takes at home compared with current hospital orders. Differences are found by fixed rules."
          : "Safety rules check medicines, results and records. Acknowledge an alert, or dismiss it with a category and a written reason. An alert closes by itself when the problem is no longer true."}
        actions={<button className="btn" onClick={() => evaluate.mutate()} disabled={evaluate.isPending}>
          {evaluate.isPending ? "Checking…" : "Re-run safety checks"}
        </button>}
      />

      <div className="tabs">
        <button className={`tab ${tab === "alerts" ? "active" : ""}`} onClick={() => setParams({ tab: "alerts" })}>
          Clinical alerts {open.length ? <span className="badge badge-critical">{open.length}</span> : null}
        </button>
        <button className={`tab ${tab === "meds" ? "active" : ""}`} onClick={() => setParams({ tab: "meds" })}>
          Medication reconciliation
        </button>
      </div>

      {error ? <div className="error-box mb-3">{error}</div> : null}

      {tab === "alerts" ? (
        <div className="split-main">
          <div className="flex-col gap-3">
            {alerts.isLoading ? <div className="loading">Loading alerts…</div> : null}
            {!open.length && !alerts.isLoading ? (
              <div className="card empty">
                <div className="empty-title">No open alerts.</div>
                <div>Run the safety rules after changing an order or confirming a result.</div>
              </div>
            ) : null}
            {open.map((alert) => (
              <div className={`alert-card ${alert.severity === "critical" ? "critical" : ""}`} key={alert.id}>
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className={`badge ${alert.severity === "critical" ? "badge-critical" : "badge-warning"}`}>
                      {alert.severity}
                    </span>
                    <span className="alert-rule">{alert.rule_id}</span>
                  </div>
                  <span className="small muted mono">{alert.id}</span>
                </div>
                <div className="alert-title mt-1">{alert.title}</div>
                <div className="alert-explanation">{alert.explanation}</div>
                <div className="flex items-center gap-2 flex-wrap">
                  {alert.evidence_event_ids.map((id) => <EvidenceChip key={id} eventIds={[id]} label="evidence" />)}
                </div>
                <div className="alert-action">{alert.recommended_action}</div>
                <div className="button-row mt-3">
                  <button className="btn btn-sm" onClick={() => acknowledge.mutate(alert.id)} disabled={acknowledge.isPending}>
                    Acknowledge
                  </button>
                  <button className="btn btn-danger btn-sm" onClick={() => { setDismissing(alert); setReason(""); setCategory(""); }}>
                    Dismiss with reason
                  </button>
                </div>
              </div>
            ))}

            {closed.length ? (
              <div className="card">
                <div className="card-head"><div className="card-title">Resolved and dismissed</div><span className="badge badge-neutral">{closed.length}</span></div>
                {closed.map((alert) => (
                  <div className={`alert-card ${alert.status} m-0`} key={alert.id} style={{ border: 0, borderBottom: "1px solid var(--border)", borderRadius: 0 }}>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className={`badge ${alert.status === "dismissed" ? "badge-warning" : "badge-success"}`}>
                          {alert.status === "resolved" ? "closed automatically" : alert.status}
                        </span>
                        <span className="alert-rule">{alert.rule_id}</span>
                      </div>
                      <span className="small muted">{alert.dismissed_by || alert.acknowledged_by || (alert.status === "resolved" ? "Rules engine" : "")}</span>
                    </div>
                    <div className="alert-title mt-1">{alert.title}</div>
                    {alert.status === "resolved" && alert.resolution ? <div className="small muted mt-1">{alert.resolution}</div> : null}
                    {alert.dismissal_category ? <div className="small muted mt-1">Category: {CATEGORY_LABEL[alert.dismissal_category]}</div> : null}
                    {alert.dismissal_reason ? <div className="small muted mt-1">Reason: {alert.dismissal_reason}</div> : null}
                  </div>
                ))}
              </div>
            ) : null}
          </div>

          <div className="flex-col gap-3">
            <div className="card">
              <div className="card-head"><div className="card-title">Why this boundary matters</div></div>
              <div className="card-pad small muted" style={{ lineHeight: 1.7 }}>
                The rule engine owns detection. The model receives the rule result and the evidence, and may not add a new alert or change severity.
                That is the answer to "what if it hallucinates a warning?"
              </div>
            </div>
            <div className="card">
              <div className="card-head"><div className="card-title">Demo rule file</div><span className="badge badge-neutral">6 rules</span></div>
              <div className="card-pad">
                <div className="check-row"><span style={{ flex: 1 }}>R1 · Metformin + eGFR &lt; 30</span><span className="badge badge-critical">critical</span></div>
                <div className="check-row"><span style={{ flex: 1 }}>R2 · Penicillin allergy conflict</span><span className="badge badge-critical">critical</span></div>
                <div className="check-row"><span style={{ flex: 1 }}>R3 · Unreviewed abnormal result</span><span className="badge badge-warning">warning</span></div>
                <div className="check-row"><span style={{ flex: 1 }}>R4 · Interacting pair</span><span className="badge badge-critical">critical</span></div>
                <div className="check-row"><span style={{ flex: 1 }}>R5 · Contradicting allergy notes</span><span className="badge badge-critical">critical</span></div>
                <div className="check-row"><span style={{ flex: 1 }}>R6 · Unresolved plan action</span><span className="badge badge-warning">warning</span></div>
                <div className="small muted mt-2">The model receives this result and its evidence. It cannot add a rule, change severity or mark the alert resolved.</div>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-col gap-3">
          <div className="grid-2">
            <div className="card">
              <div className="card-head"><div className="card-title">Home medications</div><span className="badge badge-neutral">{reconciliation.data?.home_medications.length ?? 0}</span></div>
              <table className="table">
                <thead><tr><th>Drug</th><th>Dose</th><th>Route</th><th>Frequency</th><th>Indication</th></tr></thead>
                <tbody>
                  {reconciliation.data?.home_medications.map((med) => (
                    <tr key={med.event_id}>
                      <td>{med.drug}</td>
                      <td className="mono">{med.dose}</td>
                      <td>{med.route}</td>
                      <td>{med.frequency}</td>
                      <td className="small">{med.indication || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card">
              <div className="card-head"><div className="card-title">Current inpatient plan</div><span className="badge badge-neutral">{reconciliation.data?.current_medications.length ?? 0}</span></div>
              <table className="table">
                <thead><tr><th>Drug</th><th>Dose</th><th>Route</th><th>Frequency</th><th>Indication</th></tr></thead>
                <tbody>
                  {reconciliation.data?.current_medications.map((med) => (
                    <tr key={med.event_id}>
                      <td>{med.drug}</td>
                      <td className="mono">{med.dose}</td>
                      <td>{med.route}</td>
                      <td>{med.frequency}</td>
                      <td className="small">{med.indication || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">Deterministic discrepancies</div>
                <div className="card-sub">{reconciliation.data?.summary || "Comparing home list with current orders"}</div>
              </div>
              <button className="btn btn-primary btn-sm" onClick={() => explain.mutate()} disabled={explain.isPending}>
                {explain.isPending ? <><span className="spinner" /> Drafting…</> : "Generate explanation"}
              </button>
            </div>
          </div>

          <ReconciliationQueue />
          <MedicineOrders />

          {latestRecon ? <DraftReview draft={latestRecon} /> : null}
        </div>
      )}

      {dismissing ? (
        <Modal
          title="Dismiss alert with reason"
          onClose={() => setDismissing(null)}
          footer={
            <>
              <button className="btn" onClick={() => setDismissing(null)}>Cancel</button>
              <button
                className="btn btn-danger"
                disabled={!dismissReady(category, reason) || dismiss.isPending}
                onClick={() => category && dismiss.mutate({ id: dismissing.id, reason, category })}
              >
                {dismiss.isPending ? "Dismissing…" : "Dismiss alert"}
              </button>
            </>
          }
        >
          <div className="small muted mb-2">{dismissing.title}</div>
          <DismissFields category={category} reason={reason} onCategory={setCategory} onReason={setReason} />
        </Modal>
      ) : null}
    </>
  );
}
