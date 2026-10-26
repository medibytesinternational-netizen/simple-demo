import type { Readiness } from "./types";
import { warningCount } from "./types";
import { Icon } from "../../components/icons";
import { Banner, Pill } from "../../components/ui";

export function ReadinessPanel({ readiness }: { readiness: Readiness | undefined }) {
  if (!readiness) return null;
  const missing = readiness.items.filter((item) => !item.present);
  const alerts = readiness.warnings.open_critical_alerts;
  const tasks = readiness.warnings.open_tasks;
  const differences = readiness.warnings.unresolved_medicine_differences ?? [];
  return (
    <div className="readiness">
      <ul className="checklist" aria-label="Required documentation">
        {readiness.items.map((item) => (
          <li className="check-row" key={item.key}>
            <span className={`check-mark ${item.present ? "ok" : "bad"}`} aria-hidden="true">
              <Icon name={item.present ? "check" : "alert"} size={13} />
            </span>
            <span className="check-label">{item.label}</span>
            {item.present
              ? <span className="check-source">{item.source}</span>
              : <Pill tone="critical">missing</Pill>}
          </li>
        ))}
      </ul>
      {missing.length ? (
        <Banner tone="warning" title="Missing documentation blocks discharge">
          A reason cannot replace it: {missing.map((item) => item.label).join(", ")}.
        </Banner>
      ) : null}
      {alerts.length ? (
        <Banner tone="warning" title={`Open critical alerts (${alerts.length})`}>
          <ul className="readiness-list">
            {alerts.map((alert) => <li key={alert.id}>{alert.title}</li>)}
          </ul>
        </Banner>
      ) : null}
      {tasks.length ? (
        <Banner tone="warning" title={`Open tasks (${tasks.length}). They are escalated when you discharge.`}>
          <ul className="readiness-list">
            {tasks.map((task) => <li key={task.id}>{task.title}</li>)}
          </ul>
        </Banner>
      ) : null}
      {differences.length ? (
        <Banner tone="warning" title={`Medicine differences not yet decided (${differences.length})`}>
          <ul className="readiness-list">
            {differences.map((difference) => <li key={difference.id}>{difference.title}</li>)}
          </ul>
        </Banner>
      ) : null}
      {warningCount(readiness.warnings) ? (
        <p className="small muted readiness-note">Discharging past these needs a written reason of at least 10 characters. It is recorded in the audit trail.</p>
      ) : null}
    </div>
  );
}
