import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../../api";
import type { Draft, Encounter, Leakage, Meta } from "../../types";
import { DEMO_MODE } from "../../demo/config";
import { useCan } from "../../session";
import { PageHeader } from "../../components/PageHeader";
import { DraftReview } from "../../components/DraftReview";
import { EvidenceChip } from "../../components/Evidence";
import { Icon } from "../../components/icons";
import { Banner, Drawer, EmptyState, Pill, SearchInput, Skeleton, Toolbar } from "../../components/ui";
import { CompareBar, KpiCard, SectionHead } from "../../components/insight";
import {
  byService,
  CAUSE_LABEL,
  cardOf,
  causeOf,
  findingsCsv,
  inTotal,
  isEstimate,
  num,
  prioritise,
  SERVICE_LABEL,
  totals,
  type CauseCard,
  type Finding,
} from "./leakage";

const UNAVAILABLE = DEMO_MODE ? "Amount unavailable in preview" : "Amount unavailable";

function inr(value: number) {
  return `INR ${Number(value || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}
const money = (value: unknown) => (num(value) === null ? UNAVAILABLE : inr(value as number));

function day(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const serviceLabel = (kind?: string | null) => (kind ? SERVICE_LABEL[kind] || kind.replaceAll("_", " ") : "");

/** How a finding's figures were reached, from its own fields. Missing inputs are named, not guessed. */
function Calculation({ f, estimate, encounter, block }: { f: Finding; estimate: boolean; encounter?: Encounter; block?: boolean }) {
  const qty = num(f.documented_quantity);
  const unit = num(f.unit_price);
  const expected = num(f.expected_amount);
  const billed = num(f.billed_amount);
  const gap = num(f.variance);
  if (causeOf(f) === "unsupported") {
    return <p className="leak-calc">Billed {money(f.billed_amount)} with no supporting documentation. Compliance finding; not counted as revenue at risk.</p>;
  }
  const qtyUnit = f.service_kind === "bed_day" ? "days" : "";
  const expectedText = expected === null ? UNAVAILABLE
    : qty !== null && unit !== null ? `${qty}${qtyUnit ? ` ${qtyUnit}` : ""} × ${inr(unit)} = ${inr(expected)}` : inr(expected);
  const rows: [string, ReactNode][] = [
    ["Expected", expectedText],
    ["Already billed", billed === null ? UNAVAILABLE : `${inr(billed)}${num(f.billed_quantity) === 0 ? " (none billed)" : num(f.billed_quantity) !== null ? ` (${f.billed_quantity} billed)` : ""}`],
    [estimate ? "Estimated gap" : "Gap", gap === null ? UNAVAILABLE : inr(gap)],
  ];
  return (
    <div className={`leak-calc-wrap ${block ? "is-block" : ""}`}>
      <div className={`leak-calc-grid ${block ? "is-block" : ""}`}>
        {rows.map(([label, value]) => (
          <div key={label} className={`leak-calc-row ${label.includes("gap") || label === "Gap" ? "is-gap" : ""}`}><span>{label}</span><strong>{value}</strong></div>
        ))}
      </div>
      {estimate ? (
        <p className="leak-basis">
          Counted as whole bed-days from admission{encounter?.admitted_at ? ` (${day(encounter.admitted_at)})` : ""} to today; the patient is not yet discharged, so this grows each day until discharge.
        </p>
      ) : null}
    </div>
  );
}

/**
 * Revenue leakage (/revenue?tab=leakage). Layout per docs/redesign/revenue-leakage-wireframe.md.
 * Review only: nothing here changes the bill or the claim. Figures come from GET /revenue/leakage;
 * the open-admission estimate is labelled as such and the backend total is never adjusted.
 */
export function LeakageView({ tabs }: { tabs?: ReactNode }) {
  const queryClient = useQueryClient();
  const canWork = useCan("revenue_work");
  const [cause, setCause] = useState<CauseCard | null>(null);
  const [service, setService] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Finding | null>(null);

  const leakage = useQuery<Leakage>({ queryKey: ["leakage"], queryFn: () => get("/revenue/leakage") });
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  const drafts = useQuery<{ drafts: Draft[] }>({ queryKey: ["drafts", "F13"], queryFn: () => get(`/drafts?feature=F13&limit=1`) });
  const explain = useMutation({
    mutationFn: () => post<any>("/revenue/leakage/explain"),
    onSuccess: () => queryClient.invalidateQueries(),
  });

  const data = leakage.data;
  const encounter = meta.data?.encounter;
  const findings = data?.findings ?? [];
  const loading = leakage.isLoading;
  const failed = leakage.isError;
  const latestDraft = drafts.data?.drafts?.[0];
  const t = useMemo(() => totals(data, encounter), [data, encounter]);
  const ordered = useMemo(() => prioritise(findings, encounter), [findings, encounter]);
  const services = useMemo(() => byService(findings, encounter), [findings, encounter]);
  const maxService = services ? Math.max(...services.map((s) => s.amount), 1) : 1;
  const hasKind = findings.some((f) => f.kind);
  const estimateFindings = findings.filter((f) => inTotal(f) && isEstimate(f, encounter) === true);

  const cards: { key: CauseCard; label: string; tone: "warning" | "critical"; note: string; amount: number | null }[] = useMemo(() => {
    const of = (key: CauseCard) => findings.filter((f) => cardOf(causeOf(f)) === key);
    const gapSum = (list: Finding[]) => (list.length && list.every((f) => num(f.variance) !== null) ? list.reduce((s, f) => s + (num(f.variance) ?? 0), 0) : null);
    const list: { key: CauseCard; label: string; tone: "warning" | "critical"; note: string; amount: number | null }[] = [];
    const notBilled = of("not_billed");
    list.push({ key: "not_billed", label: "Not billed", tone: "warning", note: "Documented, no bill line", amount: gapSum(notBilled) });
    if (hasKind) {
      const below = of("below_tariff");
      const estimateInBelow = below.filter((f) => isEstimate(f, encounter) === true).reduce((s, f) => s + (num(f.variance) ?? 0), 0);
      list.push({ key: "below_tariff", label: "Below tariff", tone: "warning", note: estimateInBelow ? `incl. ${inr(estimateInBelow)} open-admission estimate` : "Billed below the tariff value", amount: gapSum(below) });
      const qty = of("quantity");
      const short = qty.filter((f) => causeOf(f) === "qty_short");
      const over = qty.length - short.length;
      list.push({ key: "quantity", label: "Quantity mismatch", tone: "warning", note: over ? `${plural(over, "line")} billed above the documented quantity` : "Documented vs billed quantity", amount: short.length ? gapSum(short) : 0 });
    } else {
      list.push({ key: "below_or_qty", label: "Below tariff or short quantity", tone: "warning", note: "Not separable in this data", amount: gapSum(of("below_or_qty")) });
    }
    const unsupported = of("unsupported");
    list.push({ key: "unsupported", label: "Billed without documentation", tone: "critical", note: "Compliance · not in the total", amount: unsupported.length && unsupported.every((f) => num(f.billed_amount) !== null) ? unsupported.reduce((s, f) => s + (num(f.billed_amount) ?? 0), 0) : unsupported.length ? null : 0 });
    return list;
  }, [findings, encounter, hasKind]);
  const countOf = (key: CauseCard) => findings.filter((f) => cardOf(causeOf(f)) === key).length;

  const q = query.trim().toLowerCase();
  const visible = ordered.filter((f) =>
    (!cause || cardOf(causeOf(f)) === cause)
    && (!service || f.service_kind === service)
    && (!q || `${f.procedure} ${f.code ?? ""}`.toLowerCase().includes(q)));
  const filtered = !!cause || !!service || !!q;

  const exportCsv = () => {
    const blob = new Blob(["﻿" + findingsCsv(ordered, encounter)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `revenue-leakage-${encounter?.id || "encounter"}-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const context = encounter ? (
    <span className="small muted">
      {[encounter.kind, encounter.admitted_at ? `admitted ${day(encounter.admitted_at)}` : null, encounter.discharged_at ? `discharged ${day(encounter.discharged_at)}` : "not discharged", "compared by tariff code"].filter(Boolean).join(" · ")}
    </span>
  ) : undefined;

  return (
    <div className="insight-page pg-leakage">
      <PageHeader
        title="Revenue leakage"
        description="Documented care compared with what was billed, by tariff code. Find what is missing, why, and the evidence."
        meta={<>{context}<Pill icon="info">Review only: nothing on this page changes the bill or the claim</Pill></>}
        actions={
          <>
            <button type="button" className="btn" onClick={exportCsv} disabled={!findings.length}><Icon name="upload" size={15} className="rot-180" /> Export CSV</button>
            <button type="button" className="btn" onClick={() => window.print()} disabled={!data}><Icon name="request" size={15} /> Print</button>
          </>
        }
      />
      {tabs ? <div className="no-print">{tabs}</div> : null}
      <p className="print-only leak-print-stamp">Printed {new Date().toLocaleString("en-GB")} · figures as returned by the leakage check at that time.</p>

      {failed ? <Banner tone="danger" role="alert" title="Leakage findings could not be loaded">{(leakage.error as Error).message}</Banner> : null}

      {/* ② Revenue at risk + root causes */}
      <section className="leak-top" aria-label="Revenue at risk">
        {loading ? <div className="leak-hero" aria-busy="true"><Skeleton count={4} /></div> : (
          <div className="leak-hero">
            <span className="leak-hero-label">Revenue at risk</span>
            <span className="leak-hero-value">{t.total === null ? "—" : inr(t.total)}</span>
            <span className="leak-hero-note">{t.total === null ? UNAVAILABLE : "Gaps = expected − billed, summed by the leakage check"}</span>
            {t.total !== null ? (
              <dl className="leak-split">
                <div><dt>Billing discrepancies</dt><dd>{t.discrepancies === null ? "—" : inr(t.discrepancies)}</dd></div>
                <div className="is-estimate"><dt>Open-admission estimate</dt><dd>{inr(t.estimate)}{t.estimate ? <span className="leak-estimate-tag">Estimate</span> : null}</dd></div>
              </dl>
            ) : null}
            <span className="leak-hero-foot">
              {plural(findings.length, "finding")}
              {t.unsupportedBilled !== null ? ` · plus ${inr(t.unsupportedBilled)} billed without documentation (compliance, not in the total)` : ""}
            </span>
          </div>
        )}
        <div className="leak-causes">
          <SectionHead level={3} title="By root cause" sub={filtered && cause ? "Filtered: click the card again to clear" : "Click a card to filter the findings"} />
          <div className="leak-cause-grid">
            {cards.map((card) => (
              <KpiCard
                key={card.key}
                loading={loading}
                tone={countOf(card.key) ? card.tone : undefined}
                label={card.label}
                value={<>{countOf(card.key)}<span className={`leak-cause-amount ${card.amount === null ? "is-unavailable" : ""}`}>{card.amount === null ? UNAVAILABLE : card.amount ? inr(card.amount) : ""}</span></>}
                note={card.note}
                pressed={cause === card.key}
                onSelect={countOf(card.key) ? () => setCause(cause === card.key ? null : card.key) : undefined}
              />
            ))}
          </div>
        </div>
      </section>

      {t.mismatch ? (
        <Banner tone="warning" role="alert" title="The breakdown does not match the total">
          The findings' gaps add up to {inr(t.breakdown)}, but the leakage check reports {t.total !== null ? inr(t.total) : "no total"}. The reported total is shown unchanged; check the findings before relying on the split.
        </Banner>
      ) : null}

      <div className="insight-layout">
        {/* ④ Findings */}
        <section className="insight-panel leak-findings" aria-labelledby="leak-findings-title">
          <SectionHead id="leak-findings-title" title="Findings" count={data ? findings.length : undefined}
            sub="Confirmed discrepancies first (largest gap first), then open-admission estimates, then compliance findings." />

          {services ? (
            <div className="leak-services" aria-label="Gap by service type">
              <span className="leak-services-title">Gap by service type</span>
              <ul>
                {services.map((s) => (
                  <li key={s.kind}>
                    <button type="button" className={`leak-service ${service === s.kind ? "is-on" : ""}`} onClick={() => setService(service === s.kind ? null : s.kind)} aria-pressed={service === s.kind}>
                      <span className="leak-service-name">{serviceLabel(s.kind)}{s.estimate ? <span className="leak-estimate-tag">Estimate</span> : null}</span>
                      <span className="leak-service-track" aria-hidden="true"><span className={`leak-service-fill ${s.estimate ? "is-estimate" : ""}`} style={{ width: `${(s.amount / maxService) * 100}%` }} /></span>
                      <span className="leak-service-amount">{inr(s.amount)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : data && findings.length ? <p className="leak-services-none">Service types are not available in this data, so no service breakdown is shown.</p> : null}

          <Toolbar label="Filter findings">
            <SearchInput value={query} onChange={setQuery} placeholder="Search services or codes" label="Search findings by service or code" />
            {filtered ? <button type="button" className="btn btn-sm btn-ghost" onClick={() => { setCause(null); setService(null); setQuery(""); }}>Clear filters</button> : null}
            <span className="toolbar-count" aria-live="polite">{data ? (filtered ? `${visible.length} of ${findings.length} shown` : plural(findings.length, "finding")) : ""}</span>
          </Toolbar>

          <div className="leak-list-body">
            {loading ? <Skeleton variant="rows" count={4} /> : failed ? null : !findings.length ? (
              <EmptyState icon="check" title="No leakage findings">Every documented service has a matching bill line, and every bill line has documentation.</EmptyState>
            ) : !visible.length ? (
              <EmptyState icon="search" title="No findings match" action={<button type="button" className="btn btn-sm" onClick={() => { setCause(null); setService(null); setQuery(""); }}>Clear filters</button>}>Try another root cause, service type or search.</EmptyState>
            ) : (
              <ul className="leak-list">
                {visible.map((f) => {
                  const c = causeOf(f);
                  const estimate = inTotal(f) && isEstimate(f, encounter) === true;
                  const tone = c === "unsupported" || c === "qty_over" ? "critical" : estimate ? "estimate" : "warning";
                  return (
                    <li key={f.id} className={`leak-item tone-${tone}`}>
                      <div className="leak-item-head">
                        <div className="leak-item-title">
                          <span className={`leak-cause tone-${tone}`}>{CAUSE_LABEL[c]}</span>
                          {estimate ? <span className="leak-estimate-tag is-strong">Estimate · open admission</span> : null}
                          <h3>{f.procedure}{f.code ? <span className="mono leak-code">{f.code}</span> : null}</h3>
                          {f.service_kind ? <span className="small muted">{serviceLabel(f.service_kind)}</span> : null}
                        </div>
                        <div className="leak-item-gap">
                          <span className="leak-gap-label">{c === "unsupported" ? "Billed" : estimate ? "Estimated gap" : "Gap"}</span>
                          {num(c === "unsupported" ? f.billed_amount : f.variance) === null ? (
                            <><span className="leak-gap-value is-unavailable" aria-hidden="true">—</span><span className="leak-gap-missing">{UNAVAILABLE}</span></>
                          ) : (
                            <span className="leak-gap-value">{c === "unsupported" ? money(f.billed_amount) : money(f.variance)}</span>
                          )}
                        </div>
                      </div>
                      {num(f.variance) !== null || num(f.billed_amount) !== null ? (
                        <div className="leak-item-calc">
                          <Calculation f={f} estimate={estimate} encounter={encounter} />
                          {c !== "unsupported" ? <CompareBar billed={f.billed_amount} expected={f.expected_amount} label={f.procedure} /> : null}
                        </div>
                      ) : (
                        <p className="leak-explanation">“{f.explanation}”</p>
                      )}
                      <div className="leak-item-foot">
                        {f.documented_as ? <span className="small muted">Documented {f.documented_as}</span> : null}
                        <EvidenceChip eventIds={f.evidence_event_ids} label={`evidence (${(f.evidence_event_ids || []).length})`} />
                        <button type="button" className="btn btn-sm no-print" onClick={() => setOpen(f)} aria-label={`Details for ${f.procedure}`}>Details <Icon name="chevron" size={13} /></button>
                      </div>
                      <p className="print-only leak-explanation">“{f.explanation}”</p>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {data?.unmapped_services ? (
            <details className="leak-unmapped">
              <summary><Icon name="chevron" size={15} />Services not checked (no tariff mapping) <span className="insight-count">{data.unmapped_services.length}</span></summary>
              {data.unmapped_services.length ? (
                <ul>{data.unmapped_services.map((u, i) => <li key={`${u.label}-${i}`}><span>{u.label}</span><span className="small muted">{u.kind}</span><EvidenceChip eventIds={u.evidence_event_ids} /></li>)}</ul>
              ) : <p className="small muted">Every documented service mapped to a tariff code.</p>}
            </details>
          ) : null}
        </section>

        {/* ⑤ Rail: explain + F13 draft + method */}
        <aside className="insight-rail no-print" aria-label="Explain and method">
          <section className="rail-card leak-explain-card">
            <h2 className="rail-title">Explain</h2>
            {canWork ? (
              <button className="btn btn-primary leak-primary" onClick={() => explain.mutate()} disabled={explain.isPending} aria-busy={explain.isPending || undefined}>
                {explain.isPending ? <><span className="spinner" /> Drafting…</> : <><Icon name="spark" size={15} /> Explain findings</>}
              </button>
            ) : <p className="rail-text">Read only for your role.</p>}
            <p className="rail-text">Drafts a short review note from these findings for you to edit and approve.</p>
            {explain.isError ? <Banner tone="danger" role="alert">{(explain.error as Error).message}</Banner> : null}
          </section>
          {latestDraft ? <DraftReview draft={latestDraft} /> : (
            <section className="rail-card">
              <EmptyState icon="spark" title="No leakage explanation yet">Explain findings drafts a short review note from the deterministic findings.</EmptyState>
            </section>
          )}
          <section className="rail-card">
            <h2 className="rail-title">How this is computed</h2>
            <p className="rail-text">Documented services (procedures, medicines given, approved investigation requests, specialist consults and bed-days) are matched to bill lines by tariff code. Expected = documented quantity × tariff unit price; gap = expected − billed.</p>
            <p className="rail-text">Open admissions count whole bed-days up to today, so that figure is an estimate until discharge.{estimateFindings.length ? "" : " No open-admission estimate is in these findings."}</p>
            <p className="rail-text">MediBytes Analysis writes the explanation only.</p>
          </section>
          <section className="rail-card leak-review-only">
            <p className="rail-text"><strong>Review only.</strong> Fix the bill in the billing system; nothing here adds to the bill or the claim.</p>
          </section>
        </aside>
      </div>

      {open ? (
        <Drawer
          title={`${open.procedure}${open.code ? ` · ${open.code}` : ""}`}
          sub={[CAUSE_LABEL[causeOf(open)], serviceLabel(open.service_kind)].filter(Boolean).join(" · ")}
          onClose={() => setOpen(null)}
          footer={<span className="small muted">Review only. This page does not change the bill.</span>}
        >
          <div className="leak-drawer">
            {inTotal(open) && isEstimate(open, encounter) === true ? <span className="leak-estimate-tag is-strong">Estimate · open admission</span> : null}
            {num(open.variance) !== null || num(open.billed_amount) !== null
              ? <Calculation f={open} estimate={inTotal(open) && isEstimate(open, encounter) === true} encounter={encounter} block />
              : <p className="small muted">{DEMO_MODE ? "Amounts unavailable in preview." : "Amounts unavailable for this finding."}</p>}
            {inTotal(open) && isEstimate(open, encounter) === true ? <p className="small muted">This becomes a confirmed figure once the patient is discharged.</p> : null}
            {open.documented_as ? <p className="small"><strong>Documented</strong> {open.documented_as}{num(open.documented_quantity) !== null ? ` · quantity ${open.documented_quantity}` : ""}</p> : null}
            <div className="leak-drawer-block">
              <h3>Why</h3>
              <p>“{open.explanation}”</p>
            </div>
            <div className="leak-drawer-block">
              <h3>Evidence</h3>
              {open.evidence_event_ids?.length ? <EvidenceChip eventIds={open.evidence_event_ids} label={`${plural(open.evidence_event_ids.length, "source")}`} /> : <p className="small muted">No evidence events attached.</p>}
              {open.evidence_refs?.length ? (
                <p className="small muted">References: {open.evidence_refs.map((r) => `${r.kind.replaceAll("_", " ")} ${r.id}`).join(", ")}</p>
              ) : null}
            </div>
            <div className="leak-drawer-block">
              <h3>Counted in revenue at risk</h3>
              <p>{inTotal(open) ? "Yes" : "No: billed-without-documentation and over-billed lines are compliance findings."}</p>
            </div>
          </div>
        </Drawer>
      ) : null}
    </div>
  );
}
