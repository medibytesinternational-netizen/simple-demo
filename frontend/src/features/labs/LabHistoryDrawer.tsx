import type { Lab } from "../../types";
import { Drawer } from "../../components/ui";
import { TrendChart, type ChartPoint } from "../../components/charts";
import { formatCollected, plainNumber, SEVERITY_LABEL, severityOf, twoSidedRange, type LabPoint } from "./labStatus";

/**
 * Every recorded result for one test, from the timeline. Opened only when there are at least two;
 * the chart plots the plain-number values only, and the reference band only for a two-sided range.
 */
export function LabHistoryDrawer({ lab, series, onClose }: { lab: Lab; series: LabPoint[]; onClose: () => void }) {
  const points: ChartPoint[] = series.flatMap((point) => {
    const value = plainNumber(point.value);
    return value === null || !point.collected_at ? [] : [{ at: point.collected_at, value }];
  });
  const range = twoSidedRange(lab.reference_range);
  const newestFirst = [...series].reverse();
  return (
    <Drawer title={`${lab.name} · history`} sub={`${series.length} results on the record`} onClose={onClose}>
      <div className="lab-history">
        {points.length >= 2 ? (
          <TrendChart
            title={lab.name}
            unit={lab.unit}
            points={points}
            reference={range ? { ...range, text: String(lab.reference_range) } : { text: String(lab.reference_range || "") }}
          />
        ) : (
          <p className="small muted">The values are not all plain numbers, so no chart is drawn. Every result is listed below.</p>
        )}
        <table className="table lab-history-table">
          <caption className="sr-only">{lab.name} results, newest first</caption>
          <thead><tr><th scope="col">Collected</th><th scope="col">Value</th><th scope="col">Flag</th><th scope="col">Review</th><th scope="col">Source</th></tr></thead>
          <tbody>
            {newestFirst.map((point) => (
              <tr key={point.event_id}>
                <td>{formatCollected(point.collected_at) || "—"}</td>
                <td className="mono">{String(point.value)} {point.unit}</td>
                <td>{SEVERITY_LABEL[severityOf({ ...lab, flag: point.flag })]}</td>
                <td>{point.review_status === "unreviewed" ? "Unreviewed" : "Reviewed"}</td>
                <td className="small muted">{point.source || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="small muted">Source: laboratory results recorded on the patient timeline. Flags are as recorded with each result.</p>
      </div>
    </Drawer>
  );
}
