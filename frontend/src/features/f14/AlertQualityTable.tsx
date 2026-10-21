import { useQuery } from "@tanstack/react-query";
import { get } from "../../api";
import type { AlertQuality } from "./types";

function percent(value: number | null | undefined) {
  return value === null || value === undefined ? "n/a" : `${Math.round(value * 100)}%`;
}

export function AlertQualityTable() {
  const quality = useQuery<AlertQuality>({
    queryKey: ["alert-quality"],
    queryFn: () => get<AlertQuality>("/alerts/quality"),
    retry: false,
  });
  const data = quality.data;

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">Alert quality (small sample)</div>
          <div className="card-sub">How each safety rule has performed on the alerts it opened</div>
        </div>
        {data ? <span className="badge badge-neutral">{data.sample_size} alerts</span> : null}
      </div>
      {quality.isError ? (
        <div className="card-pad">
          <div className="banner warning">Alert quality is not available right now.</div>
        </div>
      ) : (
        <>
          <table className="table">
            <thead>
              <tr>
                <th>Rule</th>
                <th className="right">Opened</th>
                <th className="right">Still open</th>
                <th className="right">False positive</th>
                <th className="right">Known, accepted</th>
                <th className="right">Acted on</th>
                <th className="right">Auto-resolved</th>
                <th className="right">Precision</th>
              </tr>
            </thead>
            <tbody>
              {data?.rules.map((rule) => (
                <tr key={rule.rule_id}>
                  <td className="mono">{rule.rule_id}</td>
                  <td className="right">{rule.opened}</td>
                  <td className="right">{rule.open}</td>
                  <td className="right">{rule.false_positive}</td>
                  <td className="right">{rule.known_and_accepted}</td>
                  <td className="right">{rule.acted_on}</td>
                  <td className="right">{rule.auto_resolved}</td>
                  <td className="right">{percent(rule.precision)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {quality.isLoading ? <div className="card-pad small muted">Loading.</div> : null}
          {data && !data.rules.length ? <div className="empty">No alerts to measure yet.</div> : null}
          {data?.note ? <div className="card-pad small muted">{data.note}</div> : null}
        </>
      )}
    </div>
  );
}
