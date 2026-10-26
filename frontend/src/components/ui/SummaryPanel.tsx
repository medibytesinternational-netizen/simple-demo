import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon } from "../icons";

export type SummaryItem = {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: "critical" | "warning" | "success";
  to?: string;
  /** 0..1 share for the thin bar under the value. */
  share?: number;
};

const KEY = "mb-summary-collapsed:";

function readCollapsed(id: string) {
  try { return localStorage.getItem(KEY + id) === "1"; } catch { return false; }
}

/** Brisk-style collapsible summary: inline stats, each optionally a link. */
export function SummaryPanel({ id, title, items, actions }: { id: string; title: ReactNode; items: SummaryItem[]; actions?: ReactNode }) {
  const [collapsed, setCollapsed] = useState(() => readCollapsed(id));
  const toggle = () => {
    setCollapsed((v) => {
      try { localStorage.setItem(KEY + id, v ? "0" : "1"); } catch { /* remembered for this page only */ }
      return !v;
    });
  };
  return (
    <section className="summary" aria-label={typeof title === "string" ? title : undefined}>
      <div className="summary-head">
        <div className="summary-title">{title}</div>
        <div className="panel-actions">
          {actions}
          <button type="button" className="btn btn-sm" aria-expanded={!collapsed} onClick={toggle}>
            {collapsed ? "Expand" : "Collapse"}
            <Icon name="chevron" size={14} className={collapsed ? "rot-90" : "rot-270"} />
          </button>
        </div>
      </div>
      {collapsed ? null : (
        <div className="summary-body">
          {items.map((item) => {
            const content = (
              <>
                <span className="summary-label">{item.tone ? <span className="dot" style={{ color: `var(--${item.tone === "success" ? "success" : item.tone === "warning" ? "warning-solid" : "critical"})` }} /> : null}{item.label}</span>
                <span className="summary-value">{item.value}</span>
                {item.share !== undefined ? <span className="summary-bar" aria-hidden="true"><span style={{ width: `${Math.round(Math.max(0, Math.min(1, item.share)) * 100)}%` }} /></span> : null}
                {item.note ? <span className="summary-note">{item.note}</span> : null}
              </>
            );
            const cls = `summary-item ${item.tone ? `tone-${item.tone}` : ""}`;
            return item.to
              ? <Link key={item.label} to={item.to} className={cls}>{content}</Link>
              : <div key={item.label} className={cls}>{content}</div>;
          })}
        </div>
      )}
    </section>
  );
}
