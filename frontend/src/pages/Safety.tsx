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
import type { Medication } from "../types";
import { Icon } from "../components/icons";
import { Banner, DataTable, EmptyState, MetaChip, Panel, Pill, Skeleton, SummaryPanel, Tabs, Toolbar } from "../components/ui";
import type { Column } from "../components/ui";

/** The demo rule file shown in the rail. Detection lives in the backend rule engine. */
const RULES: { id: string; check: string; severity: "critical" | "warning" }[] = [
  { id: "R1", check: "Metformin + eGFR < 30", severity: "critical" },
  { id: "R2", check: "Penicillin allergy conflict", severity: "critical" },
  { id: "R3", check: "Unreviewed abnormal result", severity: "warning" },
  { id: "R4", check: "Interacting pair", severity: "critical" },
  { id: "R5", check: "Contradicting allergy notes", severity: "critical" },
  { id: "R6", check: "Unresolved plan action", severity: "warning" },
];

const MED_COLUMNS: Column<Medication>[] = [
  { key: "drug", header: "Drug", sort: (med) => med.drug, cell: (med) => <span className="cell-strong">{med.drug}</span> },
  { key: "dose", header: "Dose", cell: (med) => <span className="mono">{med.dose}</span> },
  { key: "route", header: "Route", cell: (med) => med.route },
  { key: "frequency", header: "Frequency", cell: (med) => med.frequency },
  { key: "indication", header: "Indication", cell: (med) => med.indication || <span className="muted">not documented</span> },
];

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

  const criticalOpen = open.filter((alert) => alert.severity === "critical").length;
  const discrepancyCount = reconciliation.data?.discrepancies.length ?? 0;

  return (
    <div className="page pg-safety">
      <PageHeader
        title={tab === "meds" ? "Medication reconciliation" : "Clinical alerts"}
        description={tab === "meds"
          ? "Medicines the patient takes at home compared with current hospital orders. Differences are found by fixed rules."
          : "Safety rules check medicines, results and records. Acknowledge an alert, or dismiss it with a category and a written reason. An alert closes by itself when the problem is no longer true."}
        actions={tab === "meds" ? (
          <button className="btn" onClick={() => evaluate.mutate()} disabled={evaluate.isPending} aria-busy={evaluate.isPending || undefined}>
            {evaluate.isPending ? <><span className="spinner" /> Checking…</> : <><Icon name="refresh" size={15} /> Re-run safety checks</>}
          </button>
        ) : undefined}
      />

      <Tabs
        label="Safety views"
        value={tab}
        onSelect={(key) => setParams({ tab: key })}
        items={[
          { key: "alerts", label: "Clinical alerts", count: open.length, countTone: "critical" },
          { key: "meds", label: "Medication reconciliation" },
        ]}
      />

      {error ? <Banner tone="danger" role="alert">{error}</Banner> : null}

      {tab === "alerts" ? (
        <div className="with-rail">
          <div className="section">
            <Toolbar bare label="Alert actions">
              <Pill tone={open.length ? "critical" : "success"} dot>{open.length} open</Pill>
              {criticalOpen ? <MetaChip icon="alert" tone="critical">{criticalOpen} critical</MetaChip> : null}
              <span className="toolbar-spacer" />
              <button className="btn" onClick={() => evaluate.mutate()} disabled={evaluate.isPending} aria-busy={evaluate.isPending || undefined}>
                {evaluate.isPending ? <><span className="spinner" /> Checking…</> : <><Icon name="refresh" size={15} /> Re-run safety checks</>}
              </button>
            </Toolbar>

            {alerts.isLoading ? <Skeleton variant="rows" count={3} /> : null}
            {!open.length && !alerts.isLoading ? (
              <Panel>
                <EmptyState icon="check" title="No open alerts.">
                  Re-run the safety checks after changing an order or confirming a result.
                </EmptyState>
              </Panel>
            ) : null}

            {open.length ? (
              <div className="alert-list">
                {open.map((alert) => {
                  const tone = alert.severity === "critical" ? "critical" : "warning";
                  const acking = acknowledge.isPending && acknowledge.variables === alert.id;
                  return (
                    <article className={`alert-card ${tone}`} key={alert.id} aria-labelledby={`alert-${alert.id}`}>
                      <span className="alert-icon" aria-hidden="true"><Icon name="alert" size={20} /></span>
                      <div className="alert-head">
                        <Pill tone={tone} dot>{alert.severity}</Pill>
                        <MetaChip icon="safety" title="Safety rule">Rule {alert.rule_id}</MetaChip>
                        <span className="alert-id mono">{alert.id}</span>
                      </div>
                      <h3 className="alert-title" id={`alert-${alert.id}`}>{alert.title}</h3>
                      <p className="alert-explanation">{alert.explanation}</p>
                      {alert.evidence_event_ids.length ? (
                        <div className="pill-row">
                          {alert.evidence_event_ids.map((id) => <EvidenceChip key={id} eventIds={[id]} label="evidence" />)}
                        </div>
                      ) : null}
                      <div className="alert-action">
                        <span className="alert-action-label">Recommended action</span>
                        {alert.recommended_action}
                      </div>
                      <div className="button-row alert-buttons">
                        <button className="btn btn-sm" onClick={() => acknowledge.mutate(alert.id)} disabled={acknowledge.isPending} aria-busy={acking || undefined}>
                          {acking ? <span className="spinner" /> : <Icon name="check" size={14} />}
                          Acknowledge
                        </button>
                        <button className="btn btn-danger btn-sm" onClick={() => { setDismissing(alert); setReason(""); setCategory(""); }}>
                          Dismiss with reason
                        </button>
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : null}

            {closed.length ? (
              <Panel title="Resolved and dismissed" count={closed.length} sub="Closed automatically by the rules, acknowledged, or dismissed with a reason.">
                <DataTable<AlertRow>
                  caption="Resolved and dismissed alerts"
                  rows={closed}
                  rowKey={(alert) => alert.id}
                  columns={[
                    {
                      key: "status", header: "Status", sort: (alert) => alert.status,
                      cell: (alert) => (
                        <Pill tone={alert.status === "dismissed" ? "warning" : "success"}>
                          {alert.status === "resolved" ? "closed automatically" : alert.status}
                        </Pill>
                      ),
                    },
                    { key: "rule", header: "Rule", sort: (alert) => alert.rule_id, cell: (alert) => <span className="mono">{alert.rule_id}</span> },
                    {
                      key: "title", header: "Alert", sort: (alert) => alert.title,
                      cell: (alert) => (
                        <>
                          <div className="cell-strong">{alert.title}</div>
                          {alert.status === "resolved" && alert.resolution ? <div className="cell-sub">{alert.resolution}</div> : null}
                        </>
                      ),
                    },
                    {
                      key: "by", header: "By",
                      cell: (alert) => alert.dismissed_by || alert.acknowledged_by || (alert.status === "resolved" ? "Rules engine" : ""),
                    },
                    {
                      key: "category", header: "Category",
                      cell: (alert) => alert.dismissal_category ? CATEGORY_LABEL[alert.dismissal_category] : <span className="muted">None</span>,
                    },
                    {
                      key: "reason", header: "Reason",
                      cell: (alert) => alert.dismissal_reason ? <span className="cell-action-text">{alert.dismissal_reason}</span> : <span className="muted">None</span>,
                    },
                  ]}
                />
              </Panel>
            ) : null}
          </div>

          <aside className="rail rail-sticky">
            <Panel title="How alerts work" padded>
              <div className="rail-copy">
                <p>The rule engine owns detection. The model receives the rule result and the evidence, and may not add a new alert or change severity.</p>
                <p>That is the answer to "what if it hallucinates a warning?"</p>
              </div>
            </Panel>
            <Panel
              title="Demo rule file"
              count={`${RULES.length} rules`}
              footer="The model receives this result and its evidence. It cannot add a rule, change severity or mark the alert resolved."
            >
              <table className="table rule-table">
                <caption className="sr-only">Safety rules in the demo rule file</caption>
                <thead><tr><th>Rule</th><th>Checks</th><th>Severity</th></tr></thead>
                <tbody>
                  {RULES.map((rule) => (
                    <tr key={rule.id}>
                      <td className="mono">{rule.id}</td>
                      <td>{rule.check}</td>
                      <td><Pill tone={rule.severity}>{rule.severity}</Pill></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </aside>
        </div>
      ) : (
        <div className="meds-stack">
          <SummaryPanel
            id="safety-meds"
            title={(
              <span className="recon-summary">
                <span>Deterministic discrepancies</span>
                <span className="recon-summary-text">{reconciliation.data?.summary || "Comparing home list with current orders"}</span>
              </span>
            )}
            items={[
              { label: "Home medicines", value: reconciliation.data?.home_medications.length ?? 0, note: "Taken before admission" },
              { label: "Current orders", value: reconciliation.data?.current_medications.length ?? 0, note: "Active in hospital" },
              { label: "Differences found", value: discrepancyCount, tone: discrepancyCount ? "warning" : "success", note: "Found by fixed rules" },
            ]}
            actions={(
              <button className="btn btn-primary btn-sm" onClick={() => explain.mutate()} disabled={explain.isPending} aria-busy={explain.isPending || undefined}>
                {explain.isPending ? <><span className="spinner" /> Drafting…</> : <><Icon name="spark" size={14} /> Generate explanation</>}
              </button>
            )}
          />

          <div className="split-even">
            <Panel title="Home medicines" count={reconciliation.data?.home_medications.length ?? 0} sub="What the patient takes at home">
              <DataTable<Medication>
                caption="Home medicines"
                columns={MED_COLUMNS}
                rows={reconciliation.data?.home_medications ?? []}
                rowKey={(med) => med.event_id}
                loading={reconciliation.isLoading}
                empty={<EmptyState icon="pill" title="No home medicines recorded." />}
              />
            </Panel>
            <Panel title="Current inpatient plan" count={reconciliation.data?.current_medications.length ?? 0} sub="Active hospital orders">
              <DataTable<Medication>
                caption="Current inpatient plan"
                columns={MED_COLUMNS}
                rows={reconciliation.data?.current_medications ?? []}
                rowKey={(med) => med.event_id}
                loading={reconciliation.isLoading}
                empty={<EmptyState icon="pill" title="No active orders.">Orders placed below appear here.</EmptyState>}
              />
            </Panel>
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
                aria-busy={dismiss.isPending || undefined}
              >
                {dismiss.isPending ? <><span className="spinner" /> Dismissing…</> : "Dismiss alert"}
              </button>
            </>
          }
        >
          <div className="small muted mb-2">{dismissing.title}</div>
          <DismissFields category={category} reason={reason} onCategory={setCategory} onReason={setReason} />
        </Modal>
      ) : null}
    </div>
  );
}
