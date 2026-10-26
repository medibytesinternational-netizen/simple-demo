import { useQuery } from "@tanstack/react-query";
import { get } from "../../api";
import type { AlertQuality } from "./types";
import { Banner, DataTable, EmptyState, Pill } from "../../components/ui";
import type { Column } from "../../components/ui";
import type { AlertQualityRule } from "./types";

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

  const count = (key: keyof AlertQualityRule, header: string): Column<AlertQualityRule> => ({
    key, header, align: "right", sort: (rule) => rule[key] as number, cell: (rule) => rule[key] as number,
  });
  const columns: Column<AlertQualityRule>[] = [
    { key: "rule_id", header: "Rule", sort: (rule) => rule.rule_id, cell: (rule) => <span className="mono">{rule.rule_id}</span> },
    count("opened", "Opened"),
    count("open", "Still open"),
    count("false_positive", "False positive"),
    count("known_and_accepted", "Known, accepted"),
    count("acted_on", "Acted on"),
    count("auto_resolved", "Auto-resolved"),
    { key: "precision", header: "Precision", align: "right", sort: (rule) => rule.precision, cell: (rule) => percent(rule.precision) },
  ];

  return (
    <div className="aq">
      <div className="aq-head">
        <span className="muted small">How each safety rule has performed on the alerts it opened.</span>
        {data ? <Pill>{data.sample_size} alerts</Pill> : null}
      </div>
      {quality.isError ? (
        <Banner tone="warning">Alert quality is not available right now.</Banner>
      ) : (
        <>
          <div className="aq-table">
            <DataTable
              columns={columns}
              rows={data?.rules || []}
              rowKey={(rule) => rule.rule_id}
              loading={quality.isLoading}
              caption="Alert quality by rule"
              empty={<EmptyState icon="safety" title="No alerts to measure yet">Each rule is scored here once its alerts are acted on, accepted or dismissed.</EmptyState>}
            />
          </div>
          {data?.note ? <p className="small muted m-0">{data.note}</p> : null}
        </>
      )}
    </div>
  );
}
