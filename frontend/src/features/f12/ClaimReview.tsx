import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get, openApiWindow, post } from "../../api";
import type { ClaimPrep, Draft, Meta } from "../../types";
import { DEMO_MODE } from "../../demo/config";
import { useCan } from "../../session";
import { PageHeader } from "../../components/PageHeader";
import { DraftReview } from "../../components/DraftReview";
import { EvidenceChip } from "../../components/Evidence";
import { Icon } from "../../components/icons";
import { Banner, DataTable, EmptyState, Pill, Progress, Skeleton } from "../../components/ui";
import { AttentionCard, CompareBar, KpiCard, SectionHead, apiNumber } from "../../components/insight";
import { TpaState } from "./TpaState";
import { tpaLabel, type F12Contradiction } from "./types";

type BilledItem = ClaimPrep["billed_items"][number];
type UnderbilledItem = ClaimPrep["underbilled_items"][number];

const UNAVAILABLE = DEMO_MODE ? "Amount unavailable in preview" : "Amount unavailable";

function inr(value: number) {
  return `INR ${Number(value || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function when(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Claim readiness: the backend's own `status` values only. Anything else is shown as-is, in grey. */
const READINESS: Record<string, { tone: "critical" | "warning" | "success"; icon: string; label: string }> = {
  needs_clarification: { tone: "critical", icon: "alert", label: "Clarification required" },
  on_hold: { tone: "warning", icon: "clock", label: "On hold" },
  review_ready: { tone: "success", icon: "check", label: "Ready for human review" },
};

/** Where a missing required document can be dealt with in this app (existing pages only). */
const FIX_IN: Record<string, { to: string; label: string }> = {
  signed_discharge: { to: "/discharge", label: "Fix in Discharge" },
  pre_auth: { to: "/documents?tab=followup", label: "Fix in Records follow-up" },
  lab_reports: { to: "/notes?tab=labs", label: "Open Lab results" },
};

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/**
 * Claim review (/revenue?tab=claim). Layout per docs/redesign/claim-review-wireframe.md:
 * readiness hero, financial KPI cards, ranked blockers, documents, coding checks, discrepancies,
 * and an action rail. Every figure is read from GET /revenue/claim-prep; nothing is submitted.
 */
export function ClaimReview({ tabs }: { tabs?: ReactNode }) {
  const queryClient = useQueryClient();
  const canWork = useCan("revenue_work");

  const claim = useQuery<ClaimPrep>({ queryKey: ["claim-prep"], queryFn: () => get("/revenue/claim-prep") });
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  const drafts = useQuery<{ drafts: Draft[] }>({
    queryKey: ["drafts", "F12"],
    queryFn: () => get("/drafts?feature=F12&limit=1"),
  });

  const prepare = useMutation({
    mutationFn: () => post<any>("/revenue/claim-prep/prepare"),
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const explain = useMutation({
    mutationFn: () => post<any>("/revenue/claim-prep/explain"),
    onSuccess: () => queryClient.invalidateQueries(),
  });

  const data = claim.data;
  const loading = claim.isLoading;
  const failed = claim.isError;
  const latestDraft = drafts.data?.drafts?.[0];
  const encounter = meta.data?.encounter;

  const contradictions = (data?.contradictions || []) as F12Contradiction[];
  const missing = data?.missing_documents || [];
  const unsupported = data?.unsupported_items || [];
  const required = data?.required_documents || [];
  const present = required.filter((doc) => doc.present).length;
  const blockers = contradictions.length + missing.length + unsupported.length;
  const readiness = data ? READINESS[data.status] : undefined;
  const tpaStatus = data?.tpa_review?.status;
  const tpaBlocked = tpaStatus === "needs_clarification";
  const latestPack = data?.reviews?.[0];

  const procedures = data?.documented_procedures || [];
  const codedProcedures = procedures.filter((item) => String(item.code ?? "").trim()).length;
  const billed = data?.billed_items || [];
  const supportedLines = billed.filter((item) => item.documentation_event_ids?.length).length;
  const codedLines = billed.filter((item) => String(item.code ?? "").trim()).length;

  const total = apiNumber(data?.total_amount);
  const expected = apiNumber(data?.expected_total_amount);
  const below = apiNumber(data?.underbilled_amount);
  const kpiFailed = failed ? "Unavailable: claim could not be loaded" : undefined;

  const actionError = prepare.isError || explain.isError ? (
    <Banner tone="danger" role="alert">{((prepare.error || explain.error) as Error).message}</Banner>
  ) : null;

  const context = encounter ? (
    <span className="small muted">
      {[encounter.kind, encounter.ward, encounter.bed].filter(Boolean).join(" · ")}
      {encounter.admitted_at ? ` · admitted ${when(encounter.admitted_at)}` : ""}
    </span>
  ) : undefined;

  return (
    <div className="insight-page pg-claim">
      <PageHeader
        title="Claim review"
        description="Readiness of the insurance claim pack for human review: blockers first, then documents, coding and billing."
        meta={
          <>
            {context}
            <Pill icon="info">Review only · nothing is submitted</Pill>
            {data ? (
              latestPack
                ? <Pill tone="info">Pack {latestPack.id} · {when(latestPack.prepared_at)} · {tpaLabel(latestPack.status)}</Pill>
                : <Pill>Review pack: not prepared</Pill>
            ) : null}
          </>
        }
      />
      {tabs}

      {/* ① Readiness hero: claim status and TPA review status are separate backend fields. */}
      {loading ? (
        <div className="claim-hero is-loading" aria-busy="true"><Skeleton count={3} /></div>
      ) : failed ? (
        <Banner tone="danger" role="alert" title="The claim could not be loaded">{(claim.error as Error).message}</Banner>
      ) : data ? (
        <section className={`claim-hero tone-${readiness?.tone || "neutral"}`} aria-labelledby="claim-hero-title">
          <span className="claim-hero-icon" aria-hidden="true"><Icon name={readiness?.icon || "info"} size={22} /></span>
          <div className="claim-hero-body">
            <div className="claim-hero-top">
              <h2 className="claim-hero-title" id="claim-hero-title">{readiness?.label || tpaLabel(data.status)}</h2>
              {tpaStatus ? (
                <span className={`claim-tpa-chip ${tpaBlocked ? "is-blocked" : "is-ready"}`}>
                  <Icon name={tpaBlocked ? "alert" : "check"} size={13} />
                  TPA review: {tpaBlocked ? "needs clarification" : tpaStatus === "ready_for_review" ? "ready" : tpaLabel(tpaStatus)}
                </span>
              ) : null}
            </div>
            <p className="claim-hero-lead">
              {blockers
                ? <>{plural(blockers, "item blocks", "items block")} this claim from human review.</>
                : <>Nothing is blocking human review. Nothing is submitted from here.</>}
            </p>
            {blockers ? (
              <p className="claim-hero-facts">
                {[
                  contradictions.length ? plural(contradictions.length, "contradiction") : null,
                  missing.length ? plural(missing.length, "missing document") : null,
                  unsupported.length ? plural(unsupported.length, "bill line without documentation", "bill lines without documentation") : null,
                ].filter(Boolean).join(" · ")}
              </p>
            ) : null}
          </div>
          {blockers ? <a className="btn btn-sm claim-hero-jump" href="#claim-blockers-title">Jump to blockers <Icon name="chevron" size={13} className="rot-90" /></a> : null}
        </section>
      ) : null}

      {/* ② Financial KPIs: only the amounts the API provides. There is no approved amount field. */}
      <section className="dk-kpis" aria-label="Claim at a glance">
        <KpiCard feature loading={loading} unavailable={kpiFailed || (data && total === null ? UNAVAILABLE : undefined)}
          label="Bill total" value={total !== null ? inr(total) : undefined}
          note={plural(billed.length, "bill line")} />
        <KpiCard loading={loading} unavailable={kpiFailed || (data && expected === null ? UNAVAILABLE : undefined)}
          label="Expected total" value={expected !== null ? inr(expected) : undefined}
          note="From the bill lines' expected amounts" />
        <KpiCard tone={below ? "warning" : undefined} loading={loading} unavailable={kpiFailed || (data && below === null ? UNAVAILABLE : undefined)}
          label="Below expected" value={below !== null ? inr(below) : undefined}
          note={`${plural(data?.underbilled_items?.length ?? 0, "line")} below the expected amount`} />
        <KpiCard tone={required.length && present < required.length ? "critical" : required.length ? "success" : undefined}
          loading={loading} unavailable={kpiFailed || (data && !data.required_documents ? "Not available" : undefined)}
          label="Required documents" value={`${present} of ${required.length}`}
          note={<span className="claim-kpi-progress"><Progress value={present} max={Math.max(required.length, 1)} showLabel={false} tone={present < required.length ? "critical" : "success"} />{missing.length ? `${missing.length} missing` : "All present"}</span>} />
      </section>

      <div className="claim-layout">
        {/* ③ + ④ Main column */}
        <div className="claim-main">
          <section className="insight-zone" aria-labelledby="claim-blockers-title">
            <SectionHead
              id="claim-blockers-title"
              title="Blockers"
              count={data ? blockers : undefined}
              sub="Ranked by severity: contradictions block the TPA review; missing documents and undocumented lines hold the pack."
            />
            {loading ? <div className="attn-card is-skeleton"><Skeleton count={4} /></div> : !data ? null : !blockers ? (
              <div className="insight-strip tone-success" role="status"><Icon name="check" size={16} /><span><strong>No blockers.</strong> All required documents are present and nothing contradicts the bill.</span></div>
            ) : (
              <div className="claim-blocker-groups">
                {contradictions.length ? (
                  <div className="claim-blocker-group">
                    <h3 className="claim-group-title"><span className="claim-group-dot is-critical" aria-hidden="true" />Contradictions <span className="insight-count">{contradictions.length}</span><Pill tone="critical">Critical</Pill></h3>
                    {contradictions.map((item) => (
                      <AttentionCard key={item.id} tone="critical" title={item.title} badge={<Pill tone="critical">{item.kind.replaceAll("_", " ")}</Pill>}>
                        <p className="claim-card-text">{item.explanation}</p>
                        {item.evidence?.length ? (
                          <details className="claim-sources">
                            <summary><Icon name="chevron" size={14} />Show {plural(item.evidence.length, "source")}</summary>
                            <div className="claim-source-list">
                              {item.evidence.map((source) => (
                                <div className="claim-source" key={source.event_id}>
                                  <EvidenceChip eventIds={[source.event_id]} label={source.title} />
                                  {source.quote ? <q className="small muted">{source.quote}</q> : null}
                                </div>
                              ))}
                            </div>
                          </details>
                        ) : (
                          <div className="claim-source-list"><EvidenceChip eventIds={item.evidence_event_ids} /></div>
                        )}
                      </AttentionCard>
                    ))}
                  </div>
                ) : null}

                {missing.length ? (
                  <div className="claim-blocker-group">
                    <h3 className="claim-group-title"><span className="claim-group-dot is-warning" aria-hidden="true" />Missing documents <span className="insight-count">{missing.length}</span><Pill tone="warning">Blocks review</Pill></h3>
                    <ul className="claim-row-list">
                      {missing.map((doc) => (
                        <li key={doc.key} className="claim-row tone-warning">
                          <Icon name="alert" size={16} />
                          <span className="claim-row-label">{doc.label}</span>
                          {doc.evidence_event_ids.length ? <EvidenceChip eventIds={doc.evidence_event_ids} label="evidence" /> : null}
                          {FIX_IN[doc.key] ? <Link className="btn btn-sm" to={FIX_IN[doc.key].to}>{FIX_IN[doc.key].label} <Icon name="chevron" size={13} /></Link> : <span className="small muted">Resolved outside this app</span>}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {unsupported.length ? (
                  <div className="claim-blocker-group">
                    <h3 className="claim-group-title"><span className="claim-group-dot is-warning" aria-hidden="true" />Bill lines without documentation <span className="insight-count">{unsupported.length}</span><Pill tone="warning">Holds pack</Pill></h3>
                    <ul className="claim-row-list">
                      {unsupported.map((item) => (
                        <li key={item.id} className="claim-row tone-warning">
                          <span className="mono small">{item.code}</span>
                          <span className="claim-row-label">{item.description}</span>
                          <span className="claim-row-amount">{apiNumber(item.amount) !== null ? inr(item.amount) : UNAVAILABLE}</span>
                          {item.evidence_event_ids?.length ? <EvidenceChip eventIds={item.evidence_event_ids} label="billing source" /> : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            )}
          </section>

          <section className="insight-panel claim-section" aria-labelledby="claim-docs-title">
            <SectionHead id="claim-docs-title" title="Required documents" count={data ? required.length : undefined}
              sub="Deterministic checklist for the claim pack"
              actions={data ? <span className="claim-docs-progress"><Progress value={present} max={Math.max(required.length, 1)} label={`${present} of ${required.length} present`} tone={present < required.length ? "critical" : "success"} /></span> : undefined} />
            {loading ? <div className="claim-pad"><Skeleton count={4} /></div> : (
              <ul className="claim-checklist">
                {required.map((doc) => (
                  <li key={doc.key} className={`claim-check ${doc.present ? "is-present" : "is-missing"}`}>
                    <span className="claim-check-mark" aria-hidden="true"><Icon name={doc.present ? "check" : "close"} size={13} /></span>
                    <span className="claim-row-label">{doc.label}</span>
                    <Pill tone={doc.present ? "success" : "critical"}>{doc.present ? "Present" : "Missing"}</Pill>
                    {doc.evidence_event_ids.length ? <EvidenceChip eventIds={doc.evidence_event_ids} label="evidence" /> : null}
                    {!doc.present && FIX_IN[doc.key] ? <Link className="claim-fix-link" to={FIX_IN[doc.key].to}>{FIX_IN[doc.key].label} ›</Link> : null}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="insight-panel claim-section" aria-labelledby="claim-coding-title">
            <SectionHead id="claim-coding-title" title="Coding checks" sub="Only checks the data supports" />
            {loading ? <div className="claim-pad"><Skeleton count={3} /></div> : data ? (
              <ul className="claim-checklist">
                <CodingCheck ok={codedProcedures === procedures.length} label="Documented procedures with a code" detail={procedures.length ? `${codedProcedures} of ${procedures.length}` : "No procedures documented"} />
                <CodingCheck ok={codedLines === billed.length} label="Bill lines with a code" detail={`${codedLines} of ${billed.length}`} />
                <CodingCheck ok={supportedLines === billed.length} label="Bill lines with a supporting clinical record" detail={`${supportedLines} of ${billed.length}`} />
                <li className="claim-check is-note">
                  <span className="claim-check-mark" aria-hidden="true"><Icon name="info" size={13} /></span>
                  <span className="claim-row-label">Diagnosis (ICD) codes are not checked by this system and can't be edited here.</span>
                </li>
              </ul>
            ) : null}
          </section>

          <section className="insight-panel claim-section" aria-labelledby="claim-disc-title">
            <SectionHead id="claim-disc-title" title="Billing discrepancies" count={data ? data.underbilled_items.length : undefined}
              sub="Bill lines charged below their expected amount" />
            <DataTable<UnderbilledItem>
              caption="Bill lines below the expected amount"
              rows={data?.underbilled_items || []}
              rowKey={(item) => item.id}
              loading={loading}
              empty={<EmptyState icon="check" title="No lines below expected">Every bill line meets its expected amount.</EmptyState>}
              columns={[
                {
                  key: "item", header: "Line", sort: (item) => item.description,
                  cell: (item) => <><div className="cell-strong">{item.description}</div><div className="cell-sub mono">{item.code}</div></>,
                },
                { key: "billed", header: "Billed", align: "right", sort: (item) => item.billed_amount, cell: (item) => inr(item.billed_amount) },
                { key: "expected", header: "Expected", align: "right", sort: (item) => item.expected_amount, cell: (item) => inr(item.expected_amount) },
                { key: "bar", header: <span title="Grey: expected · amber: billed">Billed vs expected</span>, cell: (item) => <CompareBar billed={item.billed_amount} expected={item.expected_amount} label={item.description} /> },
                { key: "gap", header: "Gap", align: "right", sort: (item) => item.variance, cell: (item) => <Pill tone="warning">{inr(item.variance)} below</Pill> },
                { key: "source", header: "Source", cell: (item) => <EvidenceChip eventIds={item.evidence_event_ids} label="billing source" /> },
              ]}
            />
            <div className="claim-leakage-link">
              <Icon name="leakage" size={18} />
              <span>Services documented in the record but missing from the bill are reviewed on <strong>Revenue leakage</strong>, against the tariff.</span>
              <Link className="btn btn-sm" to="/revenue?tab=leakage">Open Revenue leakage <Icon name="chevron" size={13} /></Link>
            </div>
          </section>

          <details className="insight-panel claim-fold">
            <summary><Icon name="chevron" size={15} /><span className="claim-fold-title">Patient bill</span><span className="small muted">{data ? `${plural(billed.length, "line")}${total !== null ? ` · ${inr(total)}` : ""}` : ""}</span></summary>
            <DataTable<BilledItem>
              caption="Patient bill line items"
              rows={billed}
              rowKey={(item) => item.id}
              loading={loading}
              empty={<EmptyState icon="billing" title="No bill lines">The patient bill has no line items for this stay.</EmptyState>}
              columns={[
                { key: "code", header: "Code", sort: (item) => item.code, cell: (item) => <span className="mono small">{item.code}</span> },
                { key: "description", header: "Description", sort: (item) => item.description, cell: (item) => item.description },
                { key: "amount", header: "Amount", align: "right", sort: (item) => item.amount, cell: (item) => inr(item.amount) },
                {
                  key: "documentation", header: "Documentation",
                  cell: (item) => item.documentation_event_ids.length
                    ? <EvidenceChip eventIds={item.documentation_event_ids} label="documented" />
                    : <Pill tone="critical">unsupported</Pill>,
                },
              ]}
            />
          </details>

          <details className="insight-panel claim-fold">
            <summary><Icon name="chevron" size={15} /><span className="claim-fold-title">Documented procedures</span><span className="small muted">{data ? plural(procedures.length, "procedure") : ""}</span></summary>
            <div className="claim-pad">
              {procedures.length ? (
                <ul className="claim-checklist">
                  {procedures.map((item) => (
                    <li className="claim-check" key={item.event_id}>
                      <span className="claim-row-label">{item.procedure}</span>
                      <span className="mono small muted">{item.code || "not coded"}</span>
                      <EvidenceChip eventIds={item.evidence_event_ids} label="source" />
                    </li>
                  ))}
                </ul>
              ) : <p className="small muted">No procedures documented.</p>}
            </div>
          </details>
        </div>

        {/* ⑤ Action rail: actions first (they move above the main column on small screens). */}
        <aside className="claim-actions" aria-label="Claim actions">
          <section className="rail-card claim-action-card">
            <h2 className="rail-title">Actions</h2>
            {canWork ? (
              <div className="claim-action-buttons">
                <button className="btn btn-primary claim-primary" onClick={() => prepare.mutate()} disabled={prepare.isPending} aria-busy={prepare.isPending || undefined}>
                  {prepare.isPending ? <><span className="spinner" /> Preparing…</> : <><Icon name="billing" size={16} /> Prepare review pack</>}
                </button>
                <button className="btn" onClick={() => openApiWindow("/revenue/claim-prep/pack.html")}>
                  <Icon name="link" size={15} /> Open review copy
                </button>
                <button className="btn" onClick={() => explain.mutate()} disabled={explain.isPending} aria-busy={explain.isPending || undefined}>
                  {explain.isPending ? <><span className="spinner" /> Drafting…</> : <><Icon name="spark" size={15} /> Explain gaps</>}
                </button>
              </div>
            ) : (
              <div className="claim-action-buttons">
                <button className="btn" onClick={() => openApiWindow("/revenue/claim-prep/pack.html")}>
                  <Icon name="link" size={15} /> Open review copy
                </button>
                <p className="rail-text">Read only for your role. Billing and doctors prepare and explain the pack.</p>
              </div>
            )}
            <p className="rail-text">Nothing is sent to the payer from here. The pack goes to a human review queue.</p>
            {actionError}
            {prepare.isSuccess ? (
              <Banner tone="success" role="status">
                Review {prepare.data.review.id} is {prepare.data.review.status}. Pack assembled; nothing was submitted.
              </Banner>
            ) : null}
          </section>
        </aside>

        <aside className="claim-rail" aria-label="Review status and explanation">
          <TpaState claim={data} />
          <section className="rail-card">
            <h2 className="rail-title">Review history</h2>
            {data?.reviews?.length ? (
              <ul className="claim-history">
                {data.reviews.slice(0, 4).map((review) => (
                  <li key={review.id}>
                    <span className="mono small">{review.id}</span>
                    <span className="small muted">{when(review.prepared_at)}</span>
                    <Pill tone={review.status === "review_ready" ? "success" : "warning"}>{tpaLabel(review.status)}</Pill>
                  </li>
                ))}
              </ul>
            ) : <p className="rail-text">{loading ? "Loading…" : "No packs prepared yet."}</p>}
          </section>
          {latestDraft ? <DraftReview draft={latestDraft} /> : (
            <section className="rail-card">
              <EmptyState icon="spark" title="No claim explanation yet">
                Explain gaps turns the deterministic checklist into a short review note you can edit and approve.
              </EmptyState>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}

function CodingCheck({ ok, label, detail }: { ok: boolean; label: string; detail: string }) {
  return (
    <li className={`claim-check ${ok ? "is-present" : "is-missing"}`}>
      <span className="claim-check-mark" aria-hidden="true"><Icon name={ok ? "check" : "close"} size={13} /></span>
      <span className="claim-row-label">{label}</span>
      <span className="mono small">{detail}</span>
    </li>
  );
}
