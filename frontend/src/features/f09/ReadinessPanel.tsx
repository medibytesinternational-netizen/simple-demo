import type { Readiness } from "./types";
import { warningCount } from "./types";

export function ReadinessPanel({ readiness }: { readiness: Readiness | undefined }) {
  if (!readiness) return null;
  const missing = readiness.items.filter((item) => !item.present);
  const alerts = readiness.warnings.open_critical_alerts;
  const tasks = readiness.warnings.open_tasks;
  const differences = readiness.warnings.unresolved_medicine_differences ?? [];
  return (
    <>
      <div className="checklist">
        {readiness.items.map((item) => (
          <div className="check-row" key={item.key}>
            <span className={`check-mark ${item.present ? "ok" : "bad"}`}>{item.present ? "✓" : "!"}</span>
            <span style={{ flex: 1 }}>{item.label}</span>
            <span className="small muted">{item.present ? item.source : "missing"}</span>
          </div>
        ))}
      </div>
      {missing.length ? (
        <div className="banner warning mt-3">
          Missing documentation blocks discharge, and a reason cannot replace it: {missing.map((item) => item.label).join(", ")}.
        </div>
      ) : null}
      {alerts.length ? (
        <div className="banner warning mt-3" style={{ display: "block" }}>
          <div style={{ fontWeight: 600 }}>Open critical alerts ({alerts.length})</div>
          {alerts.map((alert) => (
            <div key={alert.id} className="small">{alert.title}</div>
          ))}
        </div>
      ) : null}
      {tasks.length ? (
        <div className="banner warning mt-3" style={{ display: "block" }}>
          <div style={{ fontWeight: 600 }}>Open tasks ({tasks.length}). They are escalated when you discharge.</div>
          {tasks.map((task) => (
            <div key={task.id} className="small">{task.title}</div>
          ))}
        </div>
      ) : null}
      {differences.length ? (
        <div className="banner warning mt-3" style={{ display: "block" }}>
          <div style={{ fontWeight: 600 }}>Medicine differences not yet decided ({differences.length})</div>
          {differences.map((difference) => (
            <div key={difference.id} className="small">{difference.title}</div>
          ))}
        </div>
      ) : null}
      {warningCount(readiness.warnings) ? (
        <div className="small muted mt-2">Discharging past these needs a written reason of at least 10 characters. It is recorded in the audit trail.</div>
      ) : null}
    </>
  );
}
