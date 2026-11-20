import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get, post } from "../../api";
import type { Lab } from "../../types";
import { useCan, usePatientId } from "../../session";
import { uploadReport } from "../f08/upload";
import { Icon } from "../../components/icons";
import { Banner, EmptyState, Panel, Pill, SearchInput, Skeleton, Tabs, Toolbar } from "../../components/ui";
import { groupByPanel, isAbnormal, isUnreviewed, numeric, referenceText, severityOf } from "./panels";

const MAX_REPORT_BYTES = 12 * 1024 * 1024;

type Filter = "all" | "abnormal" | "unreviewed";
type HistoryEvent = { id: string; type: string; occurred_at: string; payload: any };
type Previous = { value: string | number; unit: string; collected: string; direction: "up" | "down" | "same" | null };

function when(value: string | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

const collectedOf = (payload: any, fallback: string) => String(payload?.collected_at || fallback || "");

/** Previous result of the same test from the patient timeline, newest first. */
function usePreviousResults(labs: Lab[]) {
  const patientId = usePatientId();
  const history = useQuery<{ events: HistoryEvent[] }>({
    queryKey: ["lab-history", patientId],
    queryFn: () => get(`/patients/${patientId}/timeline?types=lab_result&limit=500`),
    enabled: !!patientId && labs.length > 0,
  });
  return useMemo(() => {
    const out = new Map<string, Previous>();
    const events = history.data?.events || [];
    for (const lab of labs) {
      const name = lab.name.trim().toLowerCase();
      const current = Date.parse(lab.collected_at);
      const earlier = events
        .filter((e) => e.type === "lab_result" && e.id !== lab.event_id && String(e.payload?.name || "").trim().toLowerCase() === name)
        .map((e) => ({ e, at: Date.parse(collectedOf(e.payload, e.occurred_at)) }))
        .filter(({ at }) => Number.isFinite(at) && (!Number.isFinite(current) || at < current))
        .sort((a, b) => b.at - a.at)[0];
      if (!earlier) continue;
      const before = numeric(earlier.e.payload?.value);
      const now = numeric(lab.value);
      out.set(lab.event_id, {
        value: earlier.e.payload?.value,
        unit: earlier.e.payload?.unit || lab.unit,
        collected: collectedOf(earlier.e.payload, earlier.e.occurred_at),
        direction: before === null || now === null ? null : now > before ? "up" : now < before ? "down" : "same",
      });
    }
    return out;
  }, [history.data, labs]);
}

/**
 * Lab results for the open patient. Abnormal and unreviewed results come first, each
 * with its own Mark reviewed; normal results sit below and can be reviewed together.
 */
export function LabResults() {
  const queryClient = useQueryClient();
  const canUpload = useCan("upload_document");
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [labResult, setLabResult] = useState<any>(null);

  const labs = useQuery<{ labs: Lab[]; unreviewed: Lab[]; reviewed_count: number }>({
    queryKey: ["investigations"],
    queryFn: () => get("/investigations"),
  });
  const all = labs.data?.labs || [];
  const previous = usePreviousResults(all);
  // The Trend column appears only when at least one test has an earlier result.
  const hasTrend = previous.size > 0;
  const cols = hasTrend ? 7 : 6;

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
    mutationFn: (eventId: string) => post(`/labs/${eventId}/review`),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (err: any) => setError(String(err?.message || err)),
  });

  // No bulk endpoint: the existing per-result review runs once per result, each audited.
  const reviewNormal = useMutation({
    mutationFn: async (ids: string[]) => {
      for (const id of ids) await post(`/labs/${id}/review`);
    },
    onSettled: () => queryClient.invalidateQueries(),
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const busy = reviewLab.isPending || reviewNormal.isPending;
  const query = search.trim().toLowerCase();
  const visible = all.filter((lab) =>
    (!query || lab.name.toLowerCase().includes(query)) &&
    (filter === "all" || (filter === "abnormal" ? isAbnormal(lab) : isUnreviewed(lab))));
  const byRank = (a: Lab, b: Lab) => severityOf(a.flag).rank - severityOf(b.flag).rank || a.name.localeCompare(b.name);
  const needsReview = visible.filter((lab) => isAbnormal(lab) && isUnreviewed(lab)).sort(byRank);
  const abnormalReviewed = visible.filter((lab) => isAbnormal(lab) && !isUnreviewed(lab)).sort(byRank);
  const rest = visible.filter((lab) => !isAbnormal(lab)).sort(byRank);
  const normalUnreviewed = rest.filter((lab) => isUnreviewed(lab) && severityOf(lab.flag).key === "normal");

  const abnormalCount = all.filter(isAbnormal).length;
  const unreviewedCount = all.filter(isUnreviewed).length;
  const latestCollected = all.map((lab) => lab.collected_at).sort().at(-1);

  const row = (lab: Lab) => {
    const sev = severityOf(lab.flag);
    const range = referenceText(lab.reference_range);
    const prev = previous.get(lab.event_id);
    const unreviewed = isUnreviewed(lab);
    return (
      <tr key={lab.event_id} className={`lab-row sev-${sev.tone}`}>
        <td className="lab-sev"><Pill tone={sev.tone} dot>{sev.label}</Pill></td>
        <td className="lab-name">{lab.name}</td>
        <td className="lab-value"><span className="mono">{lab.value}</span> <span className="lab-unit">{lab.unit}</span></td>
        <td className="lab-range"><span className="lab-mlabel">Ref </span>{range ? <span className="mono">{range}</span> : <span className="muted">Not reported</span>}</td>
        {hasTrend ? <td className={`lab-trend ${prev ? "" : "is-empty"}`}>
          {prev ? (
            <span className={`trend trend-${prev.direction || "na"}`} title={`Previous: ${prev.value} ${prev.unit} on ${when(prev.collected)}`}>
              {prev.direction === "up" ? "↑" : prev.direction === "down" ? "↓" : prev.direction === "same" ? "→" : ""} from <span className="mono">{prev.value}</span>
            </span>
          ) : <span className="lab-none" aria-label="No earlier result">—</span>}
        </td> : null}
        <td className="lab-time"><span className="lab-mlabel">Collected </span>{when(lab.collected_at)}</td>
        <td className="lab-action">
          {unreviewed ? (
            <button
              type="button"
              className={`btn btn-sm ${isAbnormal(lab) ? "btn-primary" : ""}`}
              onClick={() => reviewLab.mutate(lab.event_id)}
              disabled={busy}
              aria-label={`Mark ${lab.name} reviewed`}
            >
              Mark reviewed
            </button>
          ) : (
            <span className="lab-reviewed"><Icon name="check" size={13} /> Reviewed</span>
          )}
        </td>
      </tr>
    );
  };

  const section = (key: string, title: string, items: Lab[], tone: "critical" | "neutral", action?: ReactNode) => (
    <tbody key={key} className="lab-section">
      <tr className={`lab-section-head tone-${tone}`}>
        <th colSpan={cols} scope="colgroup">
          <span className="lab-section-title">{title}<span className="lab-section-count">{items.length}</span></span>
          {action}
        </th>
      </tr>
      {groupByPanel(items).map((group) => [
        <tr key={`${key}-${group.panel}`} className="lab-panel-head"><th colSpan={cols} scope="colgroup">{group.panel}</th></tr>,
        ...group.labs.map(row),
      ])}
    </tbody>
  );

  return (
    <div className="lab-results">
      <Toolbar bare label="Lab result filters">
        <Tabs<Filter>
          variant="segmented"
          label="Show results"
          value={filter}
          onSelect={setFilter}
          items={[
            { key: "all", label: "All", count: all.length },
            { key: "abnormal", label: "Abnormal", count: abnormalCount },
            { key: "unreviewed", label: "Unreviewed", count: unreviewedCount },
          ]}
        />
        <SearchInput value={search} onChange={setSearch} placeholder="Search test name" />
        <span className="toolbar-spacer" />
        <span className="small muted">
          {labs.data ? `${labs.data.reviewed_count} of ${all.length} reviewed` : null}
          {latestCollected ? ` · latest ${when(latestCollected)}` : null}
        </span>
        <label
          className={`btn btn-sm ${canUpload && !uploadLab.isPending ? "" : "disabled-label"}`}
          title={canUpload ? undefined : "Your role cannot upload documents"}
        >
          {uploadLab.isPending ? <span className="spinner" /> : <Icon name="upload" size={15} />}
          Upload lab report
          <input
            type="file"
            accept="image/*,application/pdf"
            hidden
            disabled={!canUpload || uploadLab.isPending}
            onChange={(event) => {
              chooseLabReport(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </label>
      </Toolbar>

      {error ? <Banner tone="danger" role="alert">{error}</Banner> : null}
      {uploadLab.isPending ? <Banner role="status" icon={false}><span className="spinner" /> Reading report...</Banner> : null}
      {labResult ? (
        <Banner tone={labResult.ocr_status === "confirmed" || labResult.auto_committed ? "success" : "warning"} role="status">
          {labResult.ocr_status === "confirmed" || labResult.auto_committed ? (
            <div>
              Saved {Array.isArray(labResult.labs) ? labResult.labs.length : labResult.extracted?.fields?.length ?? 0} result(s) from {labResult.filename} to the record as unreviewed. They are in the table below; a doctor still reviews each one.
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
                    <td className="mono small muted">{field.reference_range || "Not reported"}</td>
                    <td>{Math.round((field.confidence ?? 0) * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </Banner>
      ) : null}

      <Panel className="lab-panel">
        {labs.isLoading ? <div className="panel-body"><Skeleton variant="table" count={5} /></div> : labs.isError ? (
          <div className="panel-body"><Banner tone="danger" role="alert">{(labs.error as Error).message}</Banner></div>
        ) : !all.length ? (
          <EmptyState icon="lab" title="No lab results">Results appear here when the laboratory reports them or a report is uploaded.</EmptyState>
        ) : !visible.length ? (
          <EmptyState icon="search" title="No matching results">Change the filter or search to see more results.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table lab-table">
              <caption className="sr-only">Lab results, abnormal and unreviewed first</caption>
              <thead>
                <tr>
                  <th scope="col">Flag</th>
                  <th scope="col">Test</th>
                  <th scope="col">Result</th>
                  <th scope="col">Reference</th>
                  {hasTrend ? <th scope="col">Trend</th> : null}
                  <th scope="col">Collected</th>
                  <th scope="col"><span className="sr-only">Review</span></th>
                </tr>
              </thead>
              {needsReview.length ? section("review", "Needs review", needsReview, "critical") : null}
              {abnormalReviewed.length ? section("abnormal", "Abnormal · reviewed", abnormalReviewed, "neutral") : null}
              {rest.length ? section("normal", "Normal & not flagged", rest, "neutral",
                normalUnreviewed.length ? (
                  <button type="button" className="btn btn-sm" onClick={() => reviewNormal.mutate(normalUnreviewed.map((lab) => lab.event_id))} disabled={busy}>
                    {reviewNormal.isPending ? <><span className="spinner" /> Marking…</> : `Mark ${normalUnreviewed.length} normal reviewed`}
                  </button>
                ) : null) : null}
            </table>
          </div>
        )}
      </Panel>
      <p className="small muted">Marking a result reviewed resolves its unreviewed-result alert and is audited. Trends compare with the previous result of the same test on the patient timeline.</p>
    </div>
  );
}
