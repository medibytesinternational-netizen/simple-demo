import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get, post } from "../../api";
import type { Lab } from "../../types";
import { useCan, usePatientId } from "../../session";
import { uploadReport } from "../f08/upload";
import { PageHeader } from "../../components/PageHeader";
import { Icon } from "../../components/icons";
import { Banner, EmptyState, Progress, SearchInput, Skeleton, Tabs, Toolbar } from "../../components/ui";
import { KpiCard, SectionHead } from "../../components/insight";
import { BulkReviewDialog } from "./BulkReviewDialog";
import { LabHistoryDrawer } from "./LabHistoryDrawer";
import { LabAttentionCard, LabRow } from "./LabParts";
import {
  compareWithPrevious,
  formatCollected,
  groupLabs,
  historyByTest,
  isAbnormal,
  isBulkReviewable,
  isUnreviewed,
  lastCollected,
  matchesFilter,
  sectionOf,
  severityOf,
  type LabFilter,
  type LabPoint,
  type SectionKey,
} from "./labStatus";

const MAX_REPORT_BYTES = 12 * 1024 * 1024;

const RANK: Record<string, number> = { critical: 0, high: 1, low: 1, abnormal: 1, unknown: 2, normal: 3 };

const GROUP_TEXT: Record<Exclude<SectionKey, "needs-review">, { title: string; sub: string }> = {
  "normal-pending": { title: "Normal, awaiting review", sub: "Flagged normal by the source; a doctor still reviews each one" },
  "reviewed-abnormal": { title: "Abnormal, reviewed", sub: "Outside the reference range and already reviewed" },
  "reviewed-other": { title: "Reviewed, normal or not flagged", sub: "No action needed" },
};

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/**
 * Lab results (/notes?tab=labs). Layout per docs/redesign/labs-wireframe.md: KPI cards, the
 * results that need a doctor's review as cards, then every result in a filterable list with a
 * rail. Upload (OCR, auto-commit as unreviewed) is unchanged; Mark reviewed also closes that
 * result's R3 alert on the server. Every figure comes from GET /investigations or the timeline.
 */
export function LabResults() {
  const queryClient = useQueryClient();
  const patientId = usePatientId();
  const [error, setError] = useState("");
  const [labResult, setLabResult] = useState<any>(null);
  const [filter, setFilter] = useState<LabFilter>("all");
  const [query, setQuery] = useState("");
  const [bulkOpen, setBulkOpen] = useState(false);
  const [historyFor, setHistoryFor] = useState<Lab | null>(null);
  const [announce, setAnnounce] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const canUpload = useCan("upload_document");
  // The server allows review_lab for some roles only; the buttons follow the same rule.
  const canReview = useCan("review_lab");

  const labs = useQuery<{ labs: Lab[]; unreviewed: Lab[]; reviewed_count: number }>({
    queryKey: ["investigations"],
    queryFn: () => get("/investigations"),
  });
  // Earlier results for the same test (COULD). Real timeline events only; if this fails the page
  // simply shows no history.
  const timeline = useQuery<{ events: any[] }>({
    queryKey: ["lab-history", patientId],
    queryFn: () => get(`/patients/${encodeURIComponent(patientId)}/timeline?types=lab_result&limit=500`),
    enabled: !!patientId,
  });

  const uploadLab = useMutation({
    mutationFn: (file: File) => uploadReport(file, "lab_report"),
    onSuccess: (result: any) => {
      setError("");
      setLabResult(result);
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const chooseLabReport = (file: File | undefined) => {
    if (!file) return;
    setError("");
    setLabResult(null);
    const name = file.name.toLowerCase();
    const readable = file.type.startsWith("image/") || file.type === "application/pdf" || /\.(pdf|png|jpe?g|gif|webp|bmp|tiff?)$/.test(name);
    if (!readable) {
      setError("Choose a PDF or an image of the report.");
      return;
    }
    if (file.size > MAX_REPORT_BYTES) {
      setError("File too large (max 12 MB).");
      return;
    }
    uploadLab.mutate(file);
  };

  const reviewLab = useMutation({
    mutationFn: (lab: Lab) => post(`/labs/${lab.event_id}/review`),
    onSuccess: (_result, lab) => {
      setError("");
      setAnnounce(`${lab.name} marked reviewed.`);
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const all = useMemo(() => labs.data?.labs ?? [], [labs.data]);
  const history = useMemo(() => historyByTest(timeline.data?.events ?? []), [timeline.data]);
  const seriesOf = (lab: Lab): LabPoint[] | undefined => history.get(String(lab.name ?? "").trim().toLowerCase());

  const counts = useMemo(() => {
    const unreviewed = all.filter(isUnreviewed);
    return {
      all: all.length,
      abnormal: all.filter(isAbnormal).length,
      abnormalReviewed: all.filter((lab) => isAbnormal(lab) && !isUnreviewed(lab)).length,
      critical: all.filter((lab) => severityOf(lab) === "critical").length,
      criticalPending: unreviewed.filter((lab) => severityOf(lab) === "critical").length,
      unreviewed: unreviewed.length,
      needsReview: unreviewed.filter((lab) => severityOf(lab) !== "normal").length,
      normalPending: all.filter(isBulkReviewable).length,
      reviewed: all.length - unreviewed.length,
    };
  }, [all]);

  // The attention zone reflects the record, not the filters: everything unreviewed that is not normal.
  const attention = useMemo(
    () => all.filter((lab) => sectionOf(lab) === "needs-review")
      .sort((a, b) => RANK[severityOf(a)] - RANK[severityOf(b)] || String(a.name).localeCompare(String(b.name))),
    [all],
  );
  const visible = useMemo(() => all.filter((lab) => matchesFilter(lab, filter, query)), [all, filter, query]);
  const groups = useMemo(() => groupLabs(visible), [visible]);
  const listGroups = groups.filter((group) => group.key !== "needs-review");
  const visibleNeedingReview = groups.find((group) => group.key === "needs-review")?.labs.length ?? 0;
  const filtered = filter !== "all" || query.trim() !== "";
  const pendingId = reviewLab.isPending ? reviewLab.variables?.event_id : undefined;
  const latest = lastCollected(all);
  const loading = labs.isLoading;
  const failed = labs.isError;

  const reviewButton = (lab: Lab, primary: boolean) => (
    <button
      type="button"
      className={`btn ${primary ? "btn-primary lab-review-primary" : "btn-sm"}`}
      onClick={() => reviewLab.mutate(lab)}
      disabled={!canReview || reviewLab.isPending}
      title={canReview ? undefined : "Your role cannot mark results reviewed"}
      aria-label={`Mark ${lab.name} reviewed`}
      aria-busy={pendingId === lab.event_id || undefined}
    >
      {pendingId === lab.event_id ? <span className="spinner" /> : <Icon name="check" size={primary ? 16 : 14} />}
      Mark reviewed
    </button>
  );

  const historyButton = (lab: Lab, small = false) => {
    const series = seriesOf(lab);
    if (!series || series.length < 2) return null;
    return (
      <button type="button" className={`btn btn-ghost ${small ? "btn-sm lab-history-link" : ""}`} onClick={() => setHistoryFor(lab)} aria-label={`${lab.name} history, ${series.length} results`}>
        <Icon name="chart" size={14} /> History ({series.length})
      </button>
    );
  };

  const filterItems = [
    { key: "all" as const, label: "All", count: counts.all, countTone: "neutral" as const },
    { key: "abnormal" as const, label: "Abnormal", count: counts.abnormal, countTone: "neutral" as const },
    { key: "unreviewed" as const, label: "Unreviewed", count: counts.unreviewed, countTone: "neutral" as const },
  ];
  const kpiUnavailable = failed ? "Unavailable: results could not be loaded" : undefined;

  return (
    <div className="insight-page pg-labs">
      <PageHeader
        title="Lab results"
        description="Latest result for each test. Results that need a doctor's review come first."
        meta={latest ? <span className="small muted">Last collected {formatCollected(latest)}</span> : undefined}
        actions={
          <>
            <button
              type="button"
              className="btn"
              onClick={() => fileInput.current?.click()}
              disabled={!canUpload || uploadLab.isPending}
              title={canUpload ? undefined : "Your role cannot upload documents"}
              aria-busy={uploadLab.isPending || undefined}
            >
              {uploadLab.isPending ? <span className="spinner" /> : <Icon name="upload" size={15} />}
              Upload lab report
            </button>
            <input
              ref={fileInput}
              type="file"
              accept="image/*,application/pdf"
              hidden
              tabIndex={-1}
              aria-hidden="true"
              onChange={(event) => {
                chooseLabReport(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
          </>
        }
      />

      <div className="sr-only" role="status" aria-live="polite">{announce}</div>
      {error ? <div className="error-box" role="alert">{error}</div> : null}

      {uploadLab.isPending ? <div className="banner" role="status"><span className="spinner" /> Reading report...</div> : null}
      {labResult ? (
        <div className={`banner ${labResult.ocr_status === "confirmed" || labResult.auto_committed ? "success" : "warning"}`} role="status">
          {labResult.ocr_status === "confirmed" || labResult.auto_committed ? (
            <div>
              Saved {Array.isArray(labResult.labs) ? labResult.labs.length : labResult.extracted?.fields?.length ?? 0} result(s) from {labResult.filename} to the record as unreviewed. They are on this page now; a doctor still reviews each one.
            </div>
          ) : labResult.ocr_status === "needs_manual_entry" ? (
            <div>
              No text could be read from {labResult.filename}. Type the values from the original in Documents. <Link to="/documents?tab=inbound">Review in Documents</Link>
            </div>
          ) : labResult.ocr_status === "needs_confirmation" ? (
            <div>
              Some values in {labResult.filename} are low confidence. Confirm them in Documents before they are saved. <Link to="/documents?tab=inbound">Review in Documents</Link>
            </div>
          ) : (
            <div>
              <div>Read {labResult.extracted?.fields?.length ?? 0} value(s) from {labResult.filename}. Nothing is saved yet. <Link to="/documents?tab=inbound">Review in Documents</Link></div>
              {labResult.auto_commit_error ? <div className="small mt-1">Automatic save did not complete: {String(labResult.auto_commit_error)}</div> : null}
            </div>
          )}
          {!(labResult.ocr_status === "confirmed" || labResult.auto_committed) && labResult.extracted?.fields?.length ? (
            <table className="table mt-2">
              <thead><tr><th>Test</th><th>Value</th><th>Reference</th><th>Confidence</th></tr></thead>
              <tbody>
                {labResult.extracted.fields.map((field: any, index: number) => (
                  <tr key={`${field.name}-${index}`}>
                    <td>{field.name}</td>
                    <td className="mono">{field.value} {field.unit}</td>
                    <td className="mono small muted">{field.reference_range || "—"}</td>
                    <td>{Math.round((field.confidence ?? 0) * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>
      ) : null}

      {/* ② KPI row: every value is a count over GET /investigations. */}
      <section className="dk-kpis" aria-label="Lab results at a glance">
        <KpiCard
          feature
          loading={loading}
          unavailable={kpiUnavailable}
          label="Pending review"
          value={counts.unreviewed}
          note={`${plural(counts.needsReview, "abnormal or unflagged", "abnormal or unflagged")} · ${counts.normalPending} normal`}
          pressed={filter === "unreviewed"}
          onSelect={() => setFilter(filter === "unreviewed" ? "all" : "unreviewed")}
        />
        <KpiCard
          tone={counts.abnormal ? "warning" : undefined}
          loading={loading}
          unavailable={kpiUnavailable}
          label="Abnormal"
          value={counts.abnormal}
          note={`${counts.abnormalReviewed} already reviewed`}
          pressed={filter === "abnormal"}
          onSelect={() => setFilter(filter === "abnormal" ? "all" : "abnormal")}
        />
        <KpiCard
          tone={counts.critical ? "critical" : undefined}
          loading={loading}
          unavailable={kpiUnavailable}
          label="Critical"
          value={counts.critical}
          note={counts.critical ? `${counts.criticalPending} awaiting review` : "None flagged critical by the source"}
        />
        <KpiCard
          loading={loading}
          unavailable={kpiUnavailable}
          label="Total tests"
          value={counts.all}
          note={`${counts.reviewed} reviewed · latest result per test`}
          onSelect={() => { setFilter("all"); setQuery(""); }}
        />
      </section>

      {/* ③ Attention zone: unreviewed results that are abnormal or not flagged. */}
      {loading ? (
        <section className="insight-zone" aria-busy="true" aria-label="Loading results that need review">
          <div className="attn-grid"><div className="attn-card is-skeleton"><Skeleton count={4} /></div><div className="attn-card is-skeleton"><Skeleton count={4} /></div></div>
        </section>
      ) : !failed && counts.all ? (
        attention.length ? (
          <section className="insight-zone labs-attention" aria-labelledby="labs-attention-title">
            <SectionHead
              id="labs-attention-title"
              title="Needs your review"
              count={attention.length}
              sub={counts.criticalPending
                ? `${plural(counts.criticalPending, "critical result")} first. Abnormal or unflagged results no doctor has reviewed yet.`
                : "Abnormal or unflagged results no doctor has reviewed yet."}
            />
            <div className="attn-grid">
              {attention.map((lab) => (
                <LabAttentionCard
                  key={lab.event_id}
                  lab={lab}
                  comparison={compareWithPrevious(lab, seriesOf(lab))}
                  reviewButton={reviewButton(lab, true)}
                  historyButton={historyButton(lab)}
                />
              ))}
            </div>
            {!canReview ? <p className="insight-note"><Icon name="info" size={14} /> View only: your role cannot mark results reviewed.</p> : null}
          </section>
        ) : (
          <div className="insight-strip tone-success" role="status">
            <Icon name="check" size={16} />
            <span><strong>Nothing waiting for review.</strong> {counts.normalPending ? `${plural(counts.normalPending, "normal result")} still awaiting review below.` : "Every abnormal result has been reviewed."}</span>
          </div>
        )
      ) : null}

      {/* ④ Workspace + ⑤ rail */}
      <div className="insight-layout">
        <section className="insight-panel labs-list" aria-labelledby="labs-all-title">
          <SectionHead id="labs-all-title" title="All results" count={loading || failed ? undefined : counts.all} sub="Reference text as supplied; the bar is drawn only for a numeric two-sided range that agrees with the flag." />
          <Toolbar label="Filter lab results">
            <Tabs label="Show" variant="segmented" items={filterItems} value={filter} onSelect={setFilter} />
            <SearchInput value={query} onChange={setQuery} placeholder="Search tests" label="Search lab tests by name" />
            <span className="toolbar-count" aria-live="polite">
              {labs.data ? (filtered ? `${visible.length} of ${counts.all} shown` : plural(counts.all, "test")) : ""}
            </span>
          </Toolbar>

          <div className="labs-list-body">
            {loading ? (
              <Skeleton variant="rows" count={4} />
            ) : failed ? (
              <Banner tone="danger" role="alert" title="Lab results could not be loaded">{(labs.error as Error).message}</Banner>
            ) : !counts.all ? (
              <EmptyState icon="lab" title="No lab results yet">
                Upload a lab report, or confirm one in <Link to="/documents?tab=inbound">Documents</Link>. Results appear here once they are on the record.
              </EmptyState>
            ) : !visible.length ? (
              <EmptyState
                icon="search"
                title="No results match"
                action={<button type="button" className="btn btn-sm" onClick={() => { setFilter("all"); setQuery(""); }}>Clear filters</button>}
              >
                {query.trim() ? <>No {filter === "all" ? "" : `${filter} `}test matches “{query.trim()}”.</> : <>No {filter} results.</>}
              </EmptyState>
            ) : (
              <>
                {visibleNeedingReview ? (
                  <a className="labs-above-note" href="#labs-attention-title">
                    <Icon name="alert" size={14} />
                    {plural(visibleNeedingReview, "matching result needs", "matching results need")} review: shown above in Needs your review
                  </a>
                ) : null}
                {listGroups.map((group) => {
                  const text = GROUP_TEXT[group.key as Exclude<SectionKey, "needs-review">];
                  const rows = (
                    <ul className="lab-list" aria-label={text.title}>
                      {group.labs.map((lab) => (
                        <LabRow
                          key={lab.event_id}
                          lab={lab}
                          comparison={compareWithPrevious(lab, seriesOf(lab))}
                          history={historyButton(lab, true)}
                          action={isUnreviewed(lab) ? reviewButton(lab, false) : null}
                        />
                      ))}
                    </ul>
                  );
                  const head = (
                    <SectionHead
                      level={3}
                      title={text.title}
                      count={group.labs.length}
                      sub={text.sub}
                      actions={group.key === "normal-pending" && canReview ? (
                        <button type="button" className="btn btn-sm" onClick={() => setBulkOpen(true)} disabled={reviewLab.isPending || !counts.normalPending}>
                          <Icon name="check" size={14} />
                          Review all normal ({counts.normalPending})
                        </button>
                      ) : undefined}
                    />
                  );
                  // Reviewed normal results need no action: folded unless they are all there is to show.
                  return group.key === "reviewed-other" ? (
                    <details key={group.key} className={`lab-group is-${group.key}`} open={filtered || listGroups.length === 1 || undefined}>
                      <summary><Icon name="chevron" size={15} />{head}</summary>
                      {rows}
                    </details>
                  ) : (
                    <div key={group.key} className={`lab-group is-${group.key}`}>{head}{rows}</div>
                  );
                })}
              </>
            )}
          </div>
        </section>

        <aside className="insight-rail" aria-label="Review status and method">
          <section className="rail-card">
            <h2 className="rail-title">Review progress</h2>
            {loading ? <Skeleton count={2} /> : failed ? <p className="small muted">Unavailable.</p> : (
              <>
                <Progress value={counts.reviewed} max={Math.max(counts.all, 1)} label={`${counts.reviewed} of ${counts.all} reviewed`} tone={counts.unreviewed ? "warning" : "success"} />
                <p className="rail-text">{counts.unreviewed ? `${plural(counts.unreviewed, "result")} still unreviewed.` : "Every result has been reviewed."}</p>
              </>
            )}
          </section>
          <section className="rail-card">
            <h2 className="rail-title">How flags work</h2>
            <p className="rail-text">High, Low and Normal come from the laboratory report or the record; MediBytes does not set them. Critical appears only when the source sends it.</p>
            <p className="rail-text">The range bar is drawn only for a numeric two-sided range that agrees with the flag; otherwise the original reference text is shown.</p>
          </section>
          <section className="rail-card">
            <h2 className="rail-title">Reviewing</h2>
            <p className="rail-text">Marking a result reviewed resolves the unreviewed-result alert and is audited.</p>
            {!canReview && !attention.length ? <p className="rail-text"><strong>View only:</strong> your role cannot mark results reviewed.</p> : null}
            {!canUpload ? <p className="rail-text">Your role cannot upload lab reports.</p> : null}
          </section>
        </aside>
      </div>

      {bulkOpen ? (
        <BulkReviewDialog
          labs={all}
          onClose={() => setBulkOpen(false)}
          onFinished={() => {
            setAnnounce("Normal results marked reviewed.");
            queryClient.invalidateQueries();
          }}
        />
      ) : null}
      {historyFor && seriesOf(historyFor) ? (
        <LabHistoryDrawer lab={historyFor} series={seriesOf(historyFor)!} onClose={() => setHistoryFor(null)} />
      ) : null}
    </div>
  );
}
