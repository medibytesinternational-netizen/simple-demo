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

  return (
    <>
      <PageHeader
        title={tab === "leakage" ? "Revenue leakage" : "Claim review"}
        description={tab === "leakage"
          ? "Care that was documented compared with what was billed. Findings are for review only."
          : "Checks the insurance claim for missing documents, underbilling and contradictions before anyone submits it."}
        meta={<span className="tag tag-neutral">Review only — nothing is submitted or charged</span>}
      />

      <div className="tabs">
        <button className={`tab ${tab === "claim" ? "active" : ""}`} onClick={() => setParams({ tab: "claim" })}>
          Claim review
        </button>
        <button className={`tab ${tab === "leakage" ? "active" : ""}`} onClick={() => setParams({ tab: "leakage" })}>
          Revenue leakage
        </button>
      </div>

      {tab === "claim" ? (
        <div className="flex-col gap-3">
          <div className="grid-4">
            <div className="card stat">
              <div className="stat-label">Seeded bill</div>
              <div className="stat-value">{claim.data ? inr(claim.data.total_amount) : "—"}</div>
              <div className="stat-note">
                {claim.data?.billed_items.length || 0} line items · expected {claim.data ? inr(claim.data.expected_total_amount) : "—"}
              </div>
            </div>
            <div className="card stat">
              <div className="stat-label">Missing documents</div>
              <div className="stat-value" style={{ color: claim.data?.missing_documents.length ? "var(--critical)" : "var(--success)" }}>
                {claim.data?.missing_documents.length ?? "—"}
              </div>
              <div className="stat-note">Blocks review readiness</div>
            </div>
            <div className="card stat">
              <div className="stat-label">Underbilled</div>
              <div className="stat-value" style={{ color: claim.data?.underbilled_items.length ? "var(--warning)" : undefined }}>
                {claim.data?.underbilled_items.length ?? "—"}
              </div>
              <div className="stat-note">
                {claim.data ? inr(claim.data.underbilled_amount) : "—"} below seeded expected value
              </div>
            </div>
            <div className="card stat">
              <div className="stat-label">Contradictions</div>
              <div className="stat-value" style={{ color: claim.data?.contradictions.length ? "var(--critical)" : "var(--success)" }}>
                {claim.data?.contradictions.length ?? "—"}
              </div>
              <div className="stat-note">
                TPA review: {claim.data?.tpa_review.status?.replaceAll("_", " ") || "—"}
              </div>
            </div>
          </div>

          <div className="split-main">
            <div className="flex-col gap-3">
              <div className="card">
                <div className="card-head">
                  <div>
                    <div className="card-title">Required documents</div>
                    <div className="card-sub">Deterministic checklist · {claim.data?.missing_documents.length ?? 0} missing</div>
                  </div>
                  <span className={`badge ${claim.data?.status === "review_ready" ? "badge-success" : "badge-warning"}`}>
                    {claim.data?.status?.replaceAll("_", " ") || "loading"}
                  </span>
                </div>
                <div className="card-pad">
                  <div className="checklist">
                    {claim.data?.required_documents.map((item) => (
                      <div className="check-row" key={item.key}>
                        <span className={`check-mark ${item.present ? "ok" : "bad"}`}>{item.present ? "✓" : "!"}</span>
                        <span style={{ flex: 1 }}>{item.label}</span>
                        <span className={`badge ${item.present ? "badge-success" : "badge-critical"}`}>{item.present ? "present" : "missing"}</span>
                        {item.evidence_event_ids.length ? <EvidenceChip eventIds={item.evidence_event_ids} label="evidence" /> : null}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="card">
                <div className="card-head">
                  <div>
                    <div className="card-title">Contradictions to resolve before review</div>
                    <div className="card-sub">Deterministic conflicts across the clinical and billing record</div>
                  </div>
                  <span className={`badge ${claim.data?.contradictions.length ? "badge-critical" : "badge-success"}`}>
                    {claim.data?.contradictions.length || 0} open
                  </span>
                </div>
                <div className="card-pad">
                  <ContradictionList items={(claim.data?.contradictions || []) as F12Contradiction[]} />
                </div>
              </div>

              <div className="card">
                <div className="card-head">
                  <div><div className="card-title">Seeded bill</div><div className="card-sub">Line items are seeded, not generated</div></div>
                  <span className="badge badge-neutral">synthetic</span>
                </div>
                <table className="table">
                  <thead><tr><th>Code</th><th>Description</th><th className="right">Amount</th><th>Documentation</th></tr></thead>
                  <tbody>
                    {claim.data?.billed_items.map((item) => (
                      <tr key={item.id}>
                        <td className="mono small">{item.code}</td>
                        <td>{item.description}</td>
                        <td className="num">{inr(item.amount)}</td>
                        <td>
                          {item.documentation_event_ids.length ? (
                            <EvidenceChip eventIds={item.documentation_event_ids} label="documented" />
                          ) : (
                            <span className="badge badge-critical">unsupported</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="card">
                <div className="card-head">
                  <div><div className="card-title">Underbilled line items</div><div className="card-sub">Billed amount is below the seeded expected amount</div></div>
                  <span className="badge badge-warning">{claim.data?.underbilled_items.length || 0}</span>
                </div>
                <div className="card-pad">
                  {claim.data?.underbilled_items.map((item) => (
                    <div className="alert-card mb-2" key={item.id} style={{ borderLeftColor: "var(--warning)" }}>
                      <div className="flex items-center justify-between gap-2">
                        <strong className="fs-13">{item.description}</strong>
                        <span className="badge badge-warning">{inr(item.variance)} below</span>
                      </div>
                      <div className="small muted">Billed {inr(item.billed_amount)} · expected {inr(item.expected_amount)}</div>
                      <div className="mt-1"><EvidenceChip eventIds={item.evidence_event_ids} label="billing source" /></div>
                    </div>
                  ))}
                  {!claim.data?.underbilled_items.length ? <div className="small muted">No underbilled line items.</div> : null}
                </div>
              </div>

              <div className="grid-2">
                <div className="card">
                  <div className="card-head"><div className="card-title">Documented but unbilled</div><span className="badge badge-warning">{claim.data?.unbilled_procedures.length || 0}</span></div>
                  <div className="card-pad">
                    {claim.data?.unbilled_procedures.map((item) => (
                      <div className="alert-card mb-2" key={item.event_id}>
                        <strong className="fs-13">{item.procedure}</strong>
                        <div className="small muted">Code {item.code || "not coded"} · found in the clinical record</div>
                        <div className="mt-1"><EvidenceChip eventIds={item.evidence_event_ids} /></div>
                      </div>
                    ))}
                    {!claim.data?.unbilled_procedures.length ? <div className="small muted">No unbilled documented procedures.</div> : null}
                  </div>
                </div>
                <div className="card">
                  <div className="card-head"><div className="card-title">Billed without documentation</div><span className="badge badge-critical">{claim.data?.unsupported_items.length || 0}</span></div>
                  <div className="card-pad">
                    {claim.data?.unsupported_items.map((item) => (
                      <div className="alert-card critical mb-2" key={item.id}>
                        <strong className="fs-13">{item.description}</strong>
                        <div className="small muted">{item.code} · {inr(item.amount)} · no supporting event</div>
                        {item.evidence_event_ids?.length ? <div className="mt-1"><EvidenceChip eventIds={item.evidence_event_ids} label="billing source" /></div> : null}
                      </div>
                    ))}
                    {!claim.data?.unsupported_items.length ? <div className="small muted">No unsupported billed items.</div> : null}
                  </div>
                </div>
              </div>
            </div>

            <div className="flex-col gap-3">
              <div className="card">
                <div className="card-head"><div><div className="card-title">Review actions</div><div className="card-sub">Human-only queue</div></div></div>
                <div className="card-pad">
                  <div className="button-row">
                    {canWork ? (
                      <button className="btn btn-primary" onClick={() => prepare.mutate()} disabled={prepare.isPending}>
                        {prepare.isPending ? <><span className="spinner" /> Preparing…</> : "Prepare review pack"}
                      </button>
                    ) : null}
                    <button className="btn" onClick={() => openApiWindow("/revenue/claim-prep/pack.html")}>
                      Open review copy
                    </button>
                    {canWork ? (
                      <button className="btn" onClick={() => explain.mutate()} disabled={explain.isPending}>
                        {explain.isPending ? <><span className="spinner" /> Drafting…</> : "Explain gaps"}
                      </button>
                    ) : null}
                  </div>
                  {!canWork ? (
                    <div className="small muted mt-2">Read only for your role. Billing and doctors prepare and explain the pack.</div>
                  ) : null}
                  {prepare.isError || explain.isError ? (
                    <div className="error-box mt-3" role="alert">{((prepare.error || explain.error) as Error).message}</div>
                  ) : null}
                  {prepare.isSuccess ? (
                    <div className="success-box mt-3">
                      Review {prepare.data.review.id} is {prepare.data.review.status}. Pack assembled; nothing was submitted.
                    </div>
                  ) : null}
                  {claim.data?.missing_documents.length ? (
                    <div className="banner warning mt-3">
                      {claim.data.discharge_signed
                        ? "The signed discharge summary is already present. The remaining blocker is listed above. "
                        : "Signing the discharge summary removes the other gap and makes the demo move. "}
                      The app cannot invent a payer document; a human must resolve the missing item.<br />
                      <span className="mono small">Review queue only. Nothing is submitted.</span>
                    </div>
                  ) : (
                    <div className="banner success mt-3">
                      All required documents are present. This pack is ready for human review; nothing is submitted.
                    </div>
                  )}
                  {claim.data?.reviews?.length ? (
                    <div className="mt-3">
                      <div className="section-label">Review history</div>
                      {claim.data.reviews.slice(0, 4).map((review) => (
                        <div className="check-row" key={review.id}>
                          <span className="mono small" style={{ flex: 1 }}>{review.id}</span>
                          <span className={`badge ${review.status === "review_ready" ? "badge-success" : "badge-warning"}`}>{review.status.replaceAll("_", " ")}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>

              <TpaState claim={claim.data} />

              <div className="card">
                <div className="card-head"><div className="card-title">Documented procedures</div><span className="badge badge-neutral">{claim.data?.documented_procedures.length || 0}</span></div>
                <div className="card-pad">
                  {claim.data?.documented_procedures.map((item) => (
                    <div className="check-row" key={item.event_id}>
                      <span style={{ flex: 1 }}>{item.procedure}</span>
                      <span className="mono small muted">{item.code}</span>
                      <EvidenceChip eventIds={item.evidence_event_ids} label="source" />
                    </div>
                  ))}
                  {!claim.data?.documented_procedures.length ? <div className="small muted">No procedures documented.</div> : null}
                </div>
              </div>

              {latest ? <DraftReview draft={latest} /> : (
                <div className="card empty"><div className="empty-title">No claim explanation yet.</div><div>Explain gaps turns the deterministic checklist into a short review note.</div></div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="split-main">
          <div className="flex-col gap-3">
            <div className="card">
              <div className="card-head">
                <div><div className="card-title">Documentation-to-billing gaps</div><div className="card-sub">{leakage.data?.summary || "Comparing documented care with the seeded bill"}</div></div>
                {canWork ? (
                  <button className="btn btn-primary btn-sm" onClick={() => explain.mutate()} disabled={explain.isPending}>
                    {explain.isPending ? <><span className="spinner" /> Drafting…</> : "Explain findings"}
                  </button>
                ) : null}
              </div>
              <div className="card-pad">
                {leakage.data?.findings.map((finding) => (
                  <div className="alert-card mb-2" key={finding.id} style={{ borderLeftColor: finding.billing_status === "unsupported" ? "var(--critical)" : "var(--warning)" }}>
                    <div className="flex items-center gap-2">
                      <span className={`badge ${finding.billing_status === "unsupported" ? "badge-critical" : "badge-warning"}`}>{finding.billing_status}</span>
                      <strong className="fs-13">{finding.procedure}</strong>
                    </div>
                    <div className="alert-explanation">{finding.explanation}</div>
                    <EvidenceChip eventIds={finding.evidence_event_ids} />
                  </div>
                ))}
                {leakage.data && !leakage.data.findings.length ? <div className="empty">No leakage findings.</div> : null}
              </div>
            </div>
          </div>
          <div className="flex-col gap-3">
            <div className="card">
              <div className="card-head"><div className="card-title">How this is computed</div></div>
              <div className="card-pad small muted" style={{ lineHeight: 1.7 }}>
                Procedures are read from timeline events of type <span className="code">procedure</span>.
                Billing lines are read from the seeded bill table. A procedure with no matching bill line is shown as unbilled; a bill line with no documentation event is shown as unsupported.
                The model writes the explanation only.
              </div>
            </div>
            {latest ? <DraftReview draft={latest} /> : (
              <div className="card empty"><div className="empty-title">No leakage explanation yet.</div><div>Generate a review note from the deterministic findings.</div></div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
