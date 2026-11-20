import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { get, openApiWindow, post } from "../api";
import type { ClaimPrep, Draft, Leakage, LeakageFinding } from "../types";
import { DraftReview } from "../components/DraftReview";
import { EvidenceChip } from "../components/Evidence";
import { useCan, usePatientId } from "../session";
import { ClaimBlockers } from "../features/f12/ClaimBlockers";
import { claimStatus } from "../features/f12/status";
import { tpaLabel, type F12TpaReview } from "../features/f12/types";
import { causeOf, departmentOf, downloadLeakageCsv, gapAmount, inr, isRecoverable } from "../features/f13/leakage";
import { PageHeader } from "../components/PageHeader";
import { Icon } from "../components/icons";
import {
  Banner,
  DataTable,
  Disclosure,
  EmptyState,
  Menu,
  MenuItem,
  Panel,
  Pill,
  Skeleton,
  Tabs,
  type Column,
} from "../components/ui";

type BilledItem = ClaimPrep["billed_items"][number];

/** Key figures in one line: label above, value below. */
function Figures({ items }: { items: { label: string; value: ReactNode; tone?: "warning" | "critical"; note?: ReactNode }[] }) {
  return (
    <dl className="rev-figures">
      {items.map((item) => (
        <div key={item.label} className={item.tone ? `tone-${item.tone}` : undefined}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
          {item.note ? <span className="rev-figure-note">{item.note}</span> : null}
        </div>
      ))}
    </dl>
  );
}

export function RevenuePage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "claim";
  const queryClient = useQueryClient();
  const canWork = useCan("revenue_work");
  const patientId = usePatientId();
  const [department, setDepartment] = useState("all");

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
  const pending = <span className="sk rev-sk" aria-label="Loading" />;

  // ---- one primary action, the rest in a menu --------------------------------------------
  const actions = (more: ReactNode) => (
    <div className="rev-actions">
      {canWork ? (
        <button className="btn btn-primary" onClick={() => prepare.mutate()} disabled={prepare.isPending} aria-busy={prepare.isPending || undefined}>
          {prepare.isPending ? <><span className="spinner" /> Preparing…</> : "Prepare review pack"}
        </button>
      ) : (
        <span className="small muted">Read only for your role.</span>
      )}
      <Menu label="More" icon="more" align="right" ariaLabel="More actions">
        {(close) => (
          <>
            {more}
            {canWork ? (
              <MenuItem icon="spark" disabled={explain.isPending} onSelect={() => { close(); explain.mutate(); }}>
                {explain.isPending ? "Drafting…" : tab === "claim" ? "Explain gaps (draft)" : "Explain findings (draft)"}
              </MenuItem>
            ) : null}
          </>
        )}
      </Menu>
    </div>
  );

  const feedback = (
    <>
      {prepare.isError || explain.isError ? (
        <Banner tone="danger" role="alert">{((prepare.error || explain.error) as Error).message}</Banner>
      ) : null}
      {explain.isPending ? <Banner role="status" icon="spark">Drafting the explanation…</Banner> : null}
      {prepare.isSuccess ? (
        <Banner tone="success" role="status">
          {tab === "claim"
            ? <>Review {prepare.data.review.id} is {String(prepare.data.review.status).replaceAll("_", " ")}. Pack assembled; nothing was submitted.</>
            : <>Review {prepare.data.review.id} recorded as {String(prepare.data.review.status).replaceAll("_", " ")}. The current billing gaps are in the claim review queue and audit log. The bill and the claim were not changed.</>}
        </Banner>
      ) : null}
    </>
  );

  const draftSection = (title: string, emptyText: string) => (
    <Disclosure title={latest ? `${title} (draft ready)` : title} defaultOpen={!!latest}>
      {latest ? <DraftReview draft={latest} /> : <p className="small muted">{emptyText}</p>}
    </Disclosure>
  );

  return (
    <div className="pg-revenue">
      <PageHeader
        title={tab === "leakage" ? "Revenue leakage" : "Claim review"}
        description={tab === "leakage"
          ? "Documented care compared with the patient bill by tariff code."
          : "What blocks this insurance claim from human review, and what the bill holds."}
        meta={<Pill icon="info">Review only: nothing is submitted or charged</Pill>}
      />

      <Tabs label="Revenue" items={[{ key: "claim", label: "Claim review" }, { key: "leakage", label: "Revenue leakage" }]} value={tab} onSelect={(key) => setParams({ tab: key })} />

      {tab === "claim" ? (
        <ClaimTab
          claim={claim.data}
          loading={claim.isLoading}
          error={claim.isError ? (claim.error as Error).message : null}
          pending={pending}
          actions={actions(
            <MenuItem icon="link" onSelect={() => openApiWindow("/revenue/claim-prep/pack.html")}>Open review copy</MenuItem>,
          )}
          feedback={feedback}
          draft={draftSection("Gap explanation", "“Explain gaps” in the More menu drafts a short review note from the checklist, for you to edit and approve.")}
        />
      ) : (
        <LeakageTab
          leakage={leakage.data}
          loading={leakage.isLoading}
          error={leakage.isError ? (leakage.error as Error).message : null}
          pending={pending}
          department={department}
          setDepartment={setDepartment}
          actions={actions(
            <MenuItem icon="list" disabled={!leakage.data?.findings.length} onSelect={() => leakage.data && downloadLeakageCsv(leakage.data.findings, patientId)}>
              Export CSV
            </MenuItem>,
          )}
          canWork={canWork}
          feedback={feedback}
          draft={draftSection("Findings explanation", "“Explain findings” in the More menu drafts a short review note from the findings above.")}
        />
      )}
    </div>
  );
}

// ==========================================================================================
// Claim review
// ==========================================================================================
function ClaimTab({ claim, loading, error, pending, actions, feedback, draft }: {
  claim?: ClaimPrep;
  loading: boolean;
  error: string | null;
  pending: ReactNode;
  actions: ReactNode;
  feedback: ReactNode;
  draft: ReactNode;
}) {
  const status = claimStatus(claim?.status);
  const tpa = claim?.tpa_review as F12TpaReview | undefined;
  const gap = claim ? Math.max(0, claim.expected_total_amount - claim.total_amount) : 0;
  const underbilledById = useMemo(
    () => new Map((claim?.underbilled_items || []).map((item) => [item.id, item])),
    [claim?.underbilled_items],
  );
  const present = claim?.required_documents.filter((d) => d.present).length ?? 0;
  const gaps = {
    unbilled: claim?.unbilled_procedures.length ?? 0,
    underbilled: claim?.underbilled_items.length ?? 0,
    unsupported: claim?.unsupported_items.length ?? 0,
  };

  const documentation = (item: BilledItem) =>
    item.documentation_event_ids.length
      ? <EvidenceChip eventIds={item.documentation_event_ids} label="Documented" />
      : <Pill tone="critical">No documentation</Pill>;

  const billColumns: Column<BilledItem>[] = [
    { key: "code", header: "Code", className: "col-hide-sm", sort: (item) => item.code, cell: (item) => <span className="mono small">{item.code}</span> },
    {
      key: "description",
      header: "Item",
      sort: (item) => item.description,
      // On narrow screens the code and documentation status move under the item name.
      cell: (item) => (
        <>
          <div>{item.description}</div>
          <div className="cell-sub mono show-sm">{item.code}</div>
          <div className="show-sm rev-cell-badge">{documentation(item)}</div>
        </>
      ),
    },
    {
      key: "amount",
      header: "Amount",
      align: "right",
      className: "nowrap",
      sort: (item) => item.amount,
      cell: (item) => {
        const under = underbilledById.get(item.id);
        return (
          <>
            <div>{inr(item.amount)}</div>
            {under ? <div className="cell-sub tone-text-warning nowrap">−{inr(under.variance)} vs tariff</div> : null}
          </>
        );
      },
    },
    {
      key: "documentation",
      header: "Documentation",
      className: "col-hide-sm",
      cell: documentation,
    },
  ];

  return (
    <>
      <section className="rev-headline" aria-label="Claim summary">
        <div className="rev-headline-main">
          <div className="rev-status">
            <Pill tone={status.tone} dot>{status.label}</Pill>
            {claim ? <span className="small muted">{status.detail} · TPA review {tpaLabel(tpa?.status)}</span> : null}
          </div>
          <Figures
            items={[
              { label: "Bill total", value: claim ? inr(claim.total_amount) : pending, note: claim ? `${claim.billed_items.length} line items` : undefined },
              { label: "Expected total", value: claim ? inr(claim.expected_total_amount) : pending },
              {
                label: "Billed below tariff",
                value: claim ? inr(gap) : pending,
                tone: gap > 0 ? "warning" : undefined,
                note: <>Unbilled items are listed separately in <Link to="/revenue?tab=leakage">Revenue leakage</Link></>,
              },
            ]}
          />
        </div>
        {actions}
      </section>

      {error ? <Banner tone="danger" role="alert">{error}</Banner> : null}
      {feedback}

      <ClaimBlockers claim={claim} loading={loading} />

      <div className="rev-grid">
        <Panel
          title="Required documents"
          sub={claim ? `${present} of ${claim.required_documents.length} present${present < claim.required_documents.length ? " · missing items are in Blockers above" : ""}` : undefined}
          footer={tpa?.evidence_event_ids?.length ? <EvidenceChip eventIds={tpa.evidence_event_ids} label="TPA evidence" /> : undefined}
          padded
        >
          {loading ? <Skeleton count={4} /> : (
            <div className="checklist">
              {claim?.required_documents.map((item) => (
                <div className="check-row" key={item.key}>
                  <span className={`check-mark ${item.present ? "ok" : "bad"}`} aria-hidden="true">
                    <Icon name={item.present ? "check" : "close"} size={13} />
                  </span>
                  <span className="check-label">{item.label}</span>
                  {item.present
                    ? (item.evidence_event_ids.length ? <EvidenceChip eventIds={item.evidence_event_ids} label="Evidence" /> : <span className="small muted">Present</span>)
                    : <Pill tone="critical">Missing</Pill>}
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Bill lines" count={claim?.billed_items.length ?? undefined} sub="From the patient account. Codes are shown as billed.">
          <DataTable<BilledItem>
            caption="Patient bill line items"
            rows={claim?.billed_items || []}
            rowKey={(item) => item.id}
            loading={loading}
            empty={<EmptyState icon="billing" title="No bill lines">The patient bill has no line items for this stay.</EmptyState>}
            columns={billColumns}
          />
        </Panel>
      </div>

      {claim ? (
        <div className="rev-gaps" role="note">
          <span className="rev-gaps-title">Billing gaps</span>
          <span>{gaps.unbilled} documented but unbilled</span>
          <span className={gaps.underbilled ? "tone-text-warning" : undefined}>
            {gaps.underbilled} billed below tariff{gaps.underbilled ? ` (${inr(claim.underbilled_amount)})` : ""}
          </span>
          {gaps.unsupported ? <span className="small muted">Undocumented bill lines are listed under Blockers.</span> : null}
          <Link className="rev-gaps-link" to="/revenue?tab=leakage">View in Revenue leakage <Icon name="chevron" size={14} /></Link>
        </div>
      ) : null}

      <div className="rev-more">
        <Disclosure title={`Review history (${claim?.reviews?.length ?? 0})`}>
          {claim?.reviews?.length ? (
            <div className="checklist">
              {claim.reviews.map((review) => (
                <div className="check-row" key={review.id}>
                  <span className="mono small check-label">{review.id}</span>
                  {review.prepared_at ? <span className="small muted">{new Date(review.prepared_at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</span> : null}
                  <Pill tone={claimStatus(review.status).tone}>{claimStatus(review.status).label}</Pill>
                </div>
              ))}
            </div>
          ) : <p className="small muted">No review pack prepared yet. The human-only review queue starts when a pack is prepared.</p>}
        </Disclosure>
        <Disclosure title={`Documented procedures (${claim?.documented_procedures.length ?? 0})`}>
          {claim?.documented_procedures.length ? (
            <div className="checklist">
              {claim.documented_procedures.map((item) => (
                <div className="check-row" key={item.event_id}>
                  <span className="check-label">{item.procedure}</span>
                  <span className="mono small muted">{item.code}</span>
                  <EvidenceChip eventIds={item.evidence_event_ids} label="source" />
                </div>
              ))}
            </div>
          ) : <p className="small muted">No procedures documented.</p>}
        </Disclosure>
        {draft}
      </div>
    </>
  );
}

// ==========================================================================================
// Revenue leakage
// ==========================================================================================
function LeakageTab({ leakage, loading, error, pending, department, setDepartment, actions, canWork, feedback, draft }: {
  leakage?: Leakage;
  loading: boolean;
  error: string | null;
  pending: ReactNode;
  department: string;
  setDepartment: (key: string) => void;
  actions: ReactNode;
  canWork: boolean;
  feedback: ReactNode;
  draft: ReactNode;
}) {
  const findings = leakage?.findings || [];
  // Largest gap first, so the most revenue is at the top.
  const recoverable = findings.filter(isRecoverable).sort((a, b) => (gapAmount(b) ?? -1) - (gapAmount(a) ?? -1));
  const unsupported = findings.filter((f) => !isRecoverable(f));
  const hasAmounts = recoverable.some((f) => gapAmount(f) !== null);
  const total = leakage?.leakage_amount ?? recoverable.reduce((sum, f) => sum + (gapAmount(f) ?? 0), 0);

  // Department filter: only departments with findings, largest gap first.
  const departments = useMemo(() => {
    const sums = new Map<string, number>();
    for (const f of findings) sums.set(departmentOf(f), (sums.get(departmentOf(f)) ?? 0) + (isRecoverable(f) ? gapAmount(f) ?? 0 : 0));
    return [...sums.entries()].sort((a, b) => b[1] - a[1]);
  }, [findings]);
  const active = departments.some(([name]) => name === department) ? department : "all";
  const inDept = (f: LeakageFinding) => active === "all" || departmentOf(f) === active;

  const itemCell = (f: LeakageFinding) => (
    <>
      <div className="cell-strong">{f.procedure}</div>
      <div className="cell-sub">
        {f.code ? <span className="mono">{f.code}</span> : "not coded"}
        {f.documented_as ? <span className="hide-sm"> · documented {f.documented_as}</span> : null}
      </div>
      <details className="rev-why">
        <summary>Why</summary>
        <p>{f.explanation}</p>
      </details>
    </>
  );
  const base: Column<LeakageFinding>[] = [
    { key: "item", header: "Item", sort: (f) => f.procedure, cell: itemCell },
    { key: "dept", header: "Department", className: "col-hide-sm", sort: departmentOf, cell: (f) => departmentOf(f) },
    { key: "cause", header: "Cause", className: "rev-cause", sort: causeOf, cell: (f) => causeOf(f) },
  ];
  const source: Column<LeakageFinding> = { key: "source", header: "Source", className: "col-hide-sm", cell: (f) => <EvidenceChip eventIds={f.evidence_event_ids} /> };

  return (
    <>
      <section className="rev-headline" aria-label="Leakage summary">
        <div className="rev-headline-main">
          <Figures
            items={[
              {
                label: "Not billed",
                value: leakage ? (hasAmounts || leakage.leakage_amount != null ? inr(total) : `${recoverable.length} items`) : pending,
                tone: recoverable.length ? "warning" : undefined,
                note: leakage ? `${recoverable.length} item${recoverable.length === 1 ? "" : "s"} documented but missing or short on the bill` : undefined,
              },
              {
                label: "Billed without documentation",
                value: leakage ? unsupported.length : pending,
                tone: unsupported.length ? "critical" : undefined,
                note: leakage ? "Not counted in the total" : undefined,
              },
            ]}
          />
          {canWork ? <p className="small muted rev-action-note">Preparing a review pack records these gaps for human review. It does not add items to the bill or change the claim.</p> : null}
        </div>
        {actions}
      </section>

      {error ? <Banner tone="danger" role="alert">{error}</Banner> : null}
      {feedback}

      {departments.length > 1 ? (
        <div className="rev-dept-filter">
        <Tabs
          variant="segmented"
          label="Filter by department"
          value={active}
          onSelect={setDepartment}
          items={[
            { key: "all", label: hasAmounts ? `All · ${inr(total)}` : "All" },
            ...departments.map(([name, sum]) => ({ key: name, label: hasAmounts && sum ? `${name} · ${inr(sum)}` : name })),
          ]}
        />
        </div>
      ) : null}

      <Panel title="Missing from the bill" count={recoverable.filter(inDept).length} sub="Documented care with no bill line, a short quantity, or a price below tariff">
        <DataTable<LeakageFinding>
          caption="Billable items missing from the bill"
          rows={recoverable.filter(inDept)}
          rowKey={(f) => f.id}
          loading={loading}
          empty={<EmptyState icon="check" title="Nothing missing from the bill">Every documented, priced service has a matching bill line.</EmptyState>}
          columns={[
            ...base,
            { key: "gap", header: "Gap", align: "right", className: "nowrap", sort: (f) => gapAmount(f), cell: (f) => <span className="rev-amount tone-text-warning">{inr(gapAmount(f))}</span> },
            source,
          ]}
        />
      </Panel>

      {unsupported.filter(inDept).length ? (
        <Panel title="Billed without documentation" count={unsupported.filter(inDept).length} sub="Bill lines with no supporting event, or more units billed than documented. Not counted in the total above.">
          <DataTable<LeakageFinding>
            caption="Bill lines without documentation"
            rows={unsupported.filter(inDept)}
            rowKey={(f) => f.id}
            columns={[
              {
                ...base[0],
                cell: (f) => (
                  <>
                    {itemCell(f)}
                    {f.code && recoverable.some((r) => r.code === f.code) ? <div className="cell-sub">Same code is also in Missing from the bill</div> : null}
                  </>
                ),
              },
              ...base.slice(1),
              { key: "billed", header: "Billed", align: "right", className: "nowrap", sort: (f) => f.billed_amount ?? null, cell: (f) => inr(f.billed_amount) },
              source,
            ]}
          />
        </Panel>
      ) : null}

      <div className="rev-more">
        {leakage?.unmapped_services?.length ? (
          <Disclosure title={`Services with no tariff code (${leakage.unmapped_services.length})`}>
            <p className="small muted">Documented, but not mapped to a tariff code, so they cannot be priced. Most are bundled in the room charge.</p>
            <div className="checklist">
              {leakage.unmapped_services.map((item, i) => (
                <div className="check-row" key={`${item.label}-${i}`}>
                  <span className="check-label">{item.label}</span>
                  <span className="small muted">{item.kind.replaceAll("_", " ")}</span>
                  <EvidenceChip eventIds={item.evidence_event_ids} />
                </div>
              ))}
            </div>
          </Disclosure>
        ) : null}
        <Disclosure title="How this is computed">
          Documented services are read from approved timeline events (procedures, medicines given, investigation requests, specialist consults) and the length of stay.
          Each is matched to a bill line by tariff code; amounts come from the tariff table. A service with no matching bill line is unbilled; a bill line with no
          documentation event is unsupported. MediBytes Analysis writes the explanation only.
        </Disclosure>
        {draft}
      </div>
    </>
  );
}
