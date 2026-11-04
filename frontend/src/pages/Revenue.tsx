import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { get, openApiWindow, post } from "../api";
import type { ClaimPrep, Draft, Leakage } from "../types";
import { DraftReview } from "../components/DraftReview";
import { EvidenceChip } from "../components/Evidence";
import { useCan } from "../session";
import { ContradictionList } from "../features/f12/ContradictionList";
import { TpaState } from "../features/f12/TpaState";
import type { F12Contradiction } from "../features/f12/types";
import { PageHeader } from "../components/PageHeader";
import { Icon } from "../components/icons";
import {
  Banner,
  DataTable,
  Disclosure,
  EmptyState,
  ListRow,
  Panel,
  Pill,
  Skeleton,
  SummaryPanel,
  Tabs,
  Toolbar,
  type SummaryItem,
} from "../components/ui";

type BilledItem = ClaimPrep["billed_items"][number];
type UnderbilledItem = ClaimPrep["underbilled_items"][number];
type UnbilledItem = ClaimPrep["unbilled_procedures"][number];
type UnsupportedItem = ClaimPrep["unsupported_items"][number];

function inr(value: number) {
  return `INR ${Number(value || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export function RevenuePage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "claim";
  const queryClient = useQueryClient();
  const canWork = useCan("revenue_work");

  const claim = useQuery<ClaimPrep>({ queryKey: ["claim-prep"], queryFn: () => get("/revenue/claim-prep") });
  const leakage = useQuery<Leakage>({
    queryKey: ["leakage"],
    queryFn: () => get("/revenue/leakage"),
    enabled: tab === "leakage",
  });
  const drafts = useQuery<{ drafts: Draft[] }>({
    queryKey: ["drafts", tab === "claim" ? "F12" : "F13"],
    queryFn: () => get(`/drafts?feature=${tab === "claim" ? "F12" : "F13"}&limit=1`),
  });

  const prepare = useMutation({
    mutationFn: () => post<any>("/revenue/claim-prep/prepare"),
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const explain = useMutation({
    mutationFn: () => post<any>(tab === "claim" ? "/revenue/claim-prep/explain" : "/revenue/leakage/explain"),
    onSuccess: () => queryClient.invalidateQueries(),
  });

  const latest = drafts.data?.drafts?.[0];
  const pendingValue = <span className="sk rev-sk" aria-label="Loading" />;
  const missingCount = claim.data?.missing_documents.length ?? 0;
  const contradictionCount = claim.data?.contradictions.length ?? 0;
  const tpaBlocked = claim.data?.tpa_review.status === "needs_clarification";
  const summaryItems: SummaryItem[] = [
    {
      label: "Bill total",
      value: claim.data ? inr(claim.data.total_amount) : pendingValue,
      note: claim.data
        ? `${claim.data.billed_items.length} line items · expected ${inr(claim.data.expected_total_amount)}`
        : "Loading the patient bill",
      share: claim.data && claim.data.expected_total_amount ? claim.data.total_amount / claim.data.expected_total_amount : undefined,
    },
    {
      label: "Missing documents",
      value: claim.data ? missingCount : pendingValue,
      tone: claim.data ? (missingCount ? "critical" : "success") : undefined,
      note: "Blocks review readiness",
    },
    {
      label: "Underbilled",
      value: claim.data ? inr(claim.data.underbilled_amount) : pendingValue,
      tone: claim.data?.underbilled_items.length ? "warning" : undefined,
      note: `${claim.data?.underbilled_items.length ?? 0} line items below the expected value`,
    },
    {
      label: "Contradictions",
      value: claim.data ? contradictionCount : pendingValue,
      tone: claim.data ? (contradictionCount ? "critical" : "success") : undefined,
      note: claim.data ? (
        <span className="rev-tpa-note">
          TPA review <Pill tone={tpaBlocked ? "critical" : "success"}>{claim.data.tpa_review.status?.replaceAll("_", " ") || "unknown"}</Pill>
        </span>
      ) : "TPA review status",
    },
  ];
  const tabItems = [
    { key: "claim", label: "Claim review" },
    { key: "leakage", label: "Revenue leakage" },
  ];
  const actionError = prepare.isError || explain.isError ? (
    <Banner tone="danger" role="alert">{((prepare.error || explain.error) as Error).message}</Banner>
  ) : null;

  return (
    <div className="pg-revenue">
      <PageHeader
        title={tab === "leakage" ? "Revenue leakage" : "Claim review"}
        description={tab === "leakage"
          ? "Care that was documented compared with what was billed. Findings are for review only."
          : "Checks the insurance claim for missing documents, underbilling and contradictions before anyone submits it."}
        meta={<Pill icon="info">Review only: nothing is submitted or charged</Pill>}
      />

      <Tabs label="Revenue" items={tabItems} value={tab} onSelect={(key) => setParams({ tab: key })} />

      {tab === "claim" ? (
        <>
          <SummaryPanel id="revenue-claim" title="Claim at a glance" items={summaryItems} />

          <Toolbar bare label="Claim review actions">
            {canWork ? (
              <button className="btn btn-primary" onClick={() => prepare.mutate()} disabled={prepare.isPending} aria-busy={prepare.isPending || undefined}>
                {prepare.isPending ? <><span className="spinner" /> Preparing…</> : "Prepare review pack"}
              </button>
            ) : null}
            <button className="btn" onClick={() => openApiWindow("/revenue/claim-prep/pack.html")}>
              <Icon name="link" size={15} />
              Open review copy
            </button>
            {canWork ? (
              <button className="btn" onClick={() => explain.mutate()} disabled={explain.isPending} aria-busy={explain.isPending || undefined}>
                {explain.isPending ? <><span className="spinner" /> Drafting…</> : <><Icon name="spark" size={15} /> Explain gaps</>}
              </button>
            ) : null}
            {!canWork ? (
              <span className="small muted">Read only for your role. Billing and doctors prepare and explain the pack.</span>
            ) : null}
          </Toolbar>

          {actionError}
          {prepare.isSuccess ? (
            <Banner tone="success" role="status">
              Review {prepare.data.review.id} is {prepare.data.review.status}. Pack assembled; nothing was submitted.
            </Banner>
          ) : null}

          <div className="with-rail">
            <div className="rev-main">
              <Panel
                title="Required documents"
                sub={`Deterministic checklist · ${missingCount} missing`}
                actions={
                  <Pill tone={claim.data?.status === "review_ready" ? "success" : "warning"} dot>
                    {claim.data?.status?.replaceAll("_", " ") || "loading"}
                  </Pill>
                }
                padded
              >
                {claim.isLoading ? <Skeleton count={4} /> : (
                  <div className="checklist">
                    {claim.data?.required_documents.map((item) => (
                      <div className="check-row" key={item.key}>
                        <span className={`check-mark ${item.present ? "ok" : "bad"}`} aria-hidden="true">
                          <Icon name={item.present ? "check" : "alert"} size={13} />
                        </span>
                        <span className="check-label">{item.label}</span>
                        <Pill tone={item.present ? "success" : "critical"}>{item.present ? "present" : "missing"}</Pill>
                        {item.evidence_event_ids.length ? <EvidenceChip eventIds={item.evidence_event_ids} label="evidence" /> : null}
                      </div>
                    ))}
                  </div>
                )}
              </Panel>

              <Panel
                title="Contradictions to resolve before review"
                sub="Deterministic conflicts across the clinical and billing record"
                actions={<Pill tone={contradictionCount ? "critical" : "success"}>{contradictionCount} open</Pill>}
                padded
              >
                {claim.isLoading ? <Skeleton count={3} /> : (
                  <ContradictionList items={(claim.data?.contradictions || []) as F12Contradiction[]} />
                )}
              </Panel>

              <Panel title="Patient bill" sub="Line items are recorded in the patient account" actions={<Pill>clinical record</Pill>}>
                <DataTable<BilledItem>
                  caption="Patient bill line items"
                  rows={claim.data?.billed_items || []}
                  rowKey={(item) => item.id}
                  loading={claim.isLoading}
                  empty={<EmptyState icon="billing" title="No bill lines">The patient bill has no line items for this stay.</EmptyState>}
                  columns={[
                    { key: "code", header: "Code", sort: (item) => item.code, cell: (item) => <span className="mono small">{item.code}</span> },
                    { key: "description", header: "Description", sort: (item) => item.description, cell: (item) => item.description },
                    { key: "amount", header: "Amount", align: "right", sort: (item) => item.amount, cell: (item) => inr(item.amount) },
                    {
                      key: "documentation",
                      header: "Documentation",
                      cell: (item) =>
                        item.documentation_event_ids.length ? (
                          <EvidenceChip eventIds={item.documentation_event_ids} label="documented" />
                        ) : (
                          <Pill tone="critical">unsupported</Pill>
                        ),
                    },
                  ]}
                />
              </Panel>

              <Panel
                title="Underbilled line items"
                sub="Billed amount is below the expected amount"
                actions={<Pill tone={claim.data?.underbilled_items.length ? "warning" : "neutral"}>{claim.data?.underbilled_items.length || 0}</Pill>}
              >
                <DataTable<UnderbilledItem>
                  caption="Underbilled line items"
                  rows={claim.data?.underbilled_items || []}
                  rowKey={(item) => item.id}
                  loading={claim.isLoading}
                  empty={<EmptyState icon="check" title="No underbilled line items">Every bill line meets its expected amount.</EmptyState>}
                  columns={[
                    {
                      key: "item",
                      header: "Line item",
                      sort: (item) => item.description,
                      cell: (item) => (
                        <>
                          <div className="cell-strong">{item.description}</div>
                          <div className="cell-sub mono">{item.code}</div>
                        </>
                      ),
                    },
                    { key: "billed", header: "Billed", align: "right", sort: (item) => item.billed_amount, cell: (item) => inr(item.billed_amount) },
                    { key: "expected", header: "Expected", align: "right", sort: (item) => item.expected_amount, cell: (item) => inr(item.expected_amount) },
                    {
                      key: "variance",
                      header: "Gap",
                      align: "right",
                      sort: (item) => item.variance,
                      cell: (item) => <Pill tone="warning">{inr(item.variance)} below</Pill>,
                    },
                    { key: "source", header: "Source", cell: (item) => <EvidenceChip eventIds={item.evidence_event_ids} label="billing source" /> },
                  ]}
                />
              </Panel>

              <div className="split-even">
                <Panel
                  title="Documented but unbilled"
                  actions={<Pill tone={claim.data?.unbilled_procedures.length ? "warning" : "neutral"}>{claim.data?.unbilled_procedures.length || 0}</Pill>}
                >
                  <DataTable<UnbilledItem>
                    caption="Documented procedures with no bill line"
                    rows={claim.data?.unbilled_procedures || []}
                    rowKey={(item) => item.event_id}
                    loading={claim.isLoading}
                    empty={<EmptyState icon="check" title="Nothing unbilled">No unbilled documented procedures.</EmptyState>}
                    columns={[
                      {
                        key: "procedure",
                        header: "Procedure",
                        sort: (item) => item.procedure,
                        cell: (item) => (
                          <>
                            <div className="cell-strong">{item.procedure}</div>
                            <div className="cell-sub">Code {item.code || "not coded"} · found in the clinical record</div>
                          </>
                        ),
                      },
                      { key: "source", header: "Source", cell: (item) => <EvidenceChip eventIds={item.evidence_event_ids} /> },
                    ]}
                  />
                </Panel>
                <Panel
                  title="Billed without documentation"
                  actions={<Pill tone={claim.data?.unsupported_items.length ? "critical" : "neutral"}>{claim.data?.unsupported_items.length || 0}</Pill>}
                >
                  <DataTable<UnsupportedItem>
                    caption="Bill lines with no supporting event"
                    rows={claim.data?.unsupported_items || []}
                    rowKey={(item) => item.id}
                    loading={claim.isLoading}
                    empty={<EmptyState icon="check" title="Nothing unsupported">No unsupported billed items.</EmptyState>}
                    columns={[
                      {
                        key: "item",
                        header: "Line item",
                        sort: (item) => item.description,
                        cell: (item) => (
                          <>
                            <div className="cell-strong">{item.description}</div>
                            <div className="cell-sub">{item.code} · no supporting event</div>
                          </>
                        ),
                      },
                      { key: "amount", header: "Amount", align: "right", sort: (item) => item.amount, cell: (item) => inr(item.amount) },
                      {
                        key: "source",
                        header: "Source",
                        cell: (item) =>
                          item.evidence_event_ids?.length ? <EvidenceChip eventIds={item.evidence_event_ids} label="billing source" /> : null,
                      },
                    ]}
                  />
                </Panel>
              </div>
            </div>

            <aside className="rail" aria-label="Review status">
              {claim.data ? (
                claim.data.missing_documents.length ? (
                  <Banner tone="warning" title="Not ready for review">
                    {claim.data.discharge_signed
                      ? "The signed discharge summary is already present. The remaining blocker is listed in Required documents. "
                      : "Signing the discharge summary removes the other gap and advances the review. "}
                    The app cannot invent a payer document; a human must resolve the missing item.
                    <div className="mono small mt-1">Review queue only. Nothing is submitted.</div>
                  </Banner>
                ) : (
                  <Banner tone="success" title="Ready for human review">
                    All required documents are present. This pack is ready for human review; nothing is submitted.
                  </Banner>
                )
              ) : null}

              {claim.data?.reviews?.length ? (
                <Panel title="Review history" sub="Human-only queue" padded>
                  <div className="checklist">
                    {claim.data.reviews.slice(0, 4).map((review) => (
                      <div className="check-row" key={review.id}>
                        <span className="mono small check-label">{review.id}</span>
                        <Pill tone={review.status === "review_ready" ? "success" : "warning"}>{review.status.replaceAll("_", " ")}</Pill>
                      </div>
                    ))}
                  </div>
                </Panel>
              ) : null}

              <TpaState claim={claim.data} />

              <Panel title="Documented procedures" count={claim.data?.documented_procedures.length || 0} padded>
                {claim.data?.documented_procedures.length ? (
                  <div className="checklist">
                    {claim.data.documented_procedures.map((item) => (
                      <div className="check-row" key={item.event_id}>
                        <span className="check-label">{item.procedure}</span>
                        <span className="mono small muted">{item.code}</span>
                        <EvidenceChip eventIds={item.evidence_event_ids} label="source" />
                      </div>
                    ))}
                  </div>
                ) : claim.isLoading ? <Skeleton count={3} /> : <div className="small muted">No procedures documented.</div>}
              </Panel>

              {latest ? <DraftReview draft={latest} /> : (
                <Panel>
                  <EmptyState icon="spark" title="No claim explanation yet">
                    Explain gaps turns the deterministic checklist into a short review note you can edit and approve.
                  </EmptyState>
                </Panel>
              )}
            </aside>
          </div>
        </>
      ) : (
        <>
          {explain.isError ? (
            <Banner tone="danger" role="alert">{(explain.error as Error).message}</Banner>
          ) : null}
          <div className="with-rail">
            <Panel
              title="Documentation-to-billing gaps"
              sub={leakage.data?.summary || "Comparing documented care with the patient bill"}
            >
              <Toolbar label="Leakage actions">
                <span className="small muted">{leakage.data?.findings.length ?? 0} findings</span>
                <span className="toolbar-spacer" />
                {canWork ? (
                  <button className="btn btn-primary btn-sm" onClick={() => explain.mutate()} disabled={explain.isPending} aria-busy={explain.isPending || undefined}>
                    {explain.isPending ? <><span className="spinner" /> Drafting…</> : <><Icon name="spark" size={15} /> Explain findings</>}
                  </button>
                ) : (
                  <span className="small muted">Read only for your role.</span>
                )}
              </Toolbar>
              <div className="panel-body">
                {leakage.isLoading ? <Skeleton variant="rows" count={3} /> : leakage.data?.findings.length ? (
                  <div className="rows">
                    {leakage.data.findings.map((finding) => (
                      <ListRow
                        key={finding.id}
                        icon="leakage"
                        tone={finding.billing_status === "unsupported" ? "critical" : "warning"}
                        title={finding.procedure}
                        body={finding.explanation}
                        chips={
                          <>
                            <Pill tone={finding.billing_status === "unsupported" ? "critical" : "warning"} dot>{finding.billing_status}</Pill>
                            <EvidenceChip eventIds={finding.evidence_event_ids} />
                          </>
                        }
                      />
                    ))}
                  </div>
                ) : leakage.data ? (
                  <EmptyState icon="check" title="No leakage findings">
                    Every documented procedure has a bill line, and every bill line has documentation.
                  </EmptyState>
                ) : null}
              </div>
            </Panel>

            <aside className="rail" aria-label="About these findings">
              <Disclosure title="How this is computed" defaultOpen>
                Procedures are read from timeline events of type <span className="code">procedure</span>.
                Billing lines are read from the patient account. A procedure with no matching bill line is shown as unbilled; a bill line with no documentation event is shown as unsupported.
                MediBytes Analysis writes the explanation only.
              </Disclosure>
              {latest ? <DraftReview draft={latest} /> : (
                <Panel>
                  <EmptyState icon="spark" title="No leakage explanation yet">
                    Explain findings drafts a short review note from the deterministic findings above.
                  </EmptyState>
                </Panel>
              )}
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
