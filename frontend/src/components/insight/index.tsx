// Shared building blocks for the redesigned review pages (Lab results, Claim review, Revenue
// leakage): KPI cards bound to real data, attention cards and section heads. Styles live in
// styles/pages/insight.css and reuse the dashboard's dk-kpi cards.
import type { ReactNode } from "react";
import { Skeleton } from "../ui";

export type KpiTone = "critical" | "warning" | "success";

/**
 * One KPI card. `value` comes straight from the API; when the data is missing pass `unavailable`
 * (the reason) and the card shows "—" with it, never a substitute number.
 */
export function KpiCard({ label, value, note, tone, feature, pressed, onSelect, loading, unavailable }: {
  label: string;
  value?: ReactNode;
  note?: ReactNode;
  tone?: KpiTone;
  /** The page's hero metric: the navy feature card. */
  feature?: boolean;
  /** When set, the card is a filter button. */
  pressed?: boolean;
  onSelect?: () => void;
  loading?: boolean;
  unavailable?: string;
}) {
  const cls = `dk-kpi insight-kpi ${feature ? "is-feature" : ""} ${tone && !unavailable ? `tone-${tone}` : ""} ${pressed ? "is-on" : ""}`;
  if (loading) {
    return <div className="dk-kpi insight-kpi" aria-busy="true" aria-label={`${label}: loading`}><Skeleton count={3} /></div>;
  }
  const body = (
    <>
      <span className="dk-kpi-label">{label}</span>
      <span className="dk-kpi-value">{unavailable ? "—" : value}</span>
      <span className="dk-kpi-note">{unavailable || note}</span>
    </>
  );
  return onSelect && !unavailable ? (
    <button type="button" className={cls} onClick={onSelect} aria-pressed={pressed === undefined ? undefined : pressed}>{body}</button>
  ) : (
    <div className={cls}>{body}</div>
  );
}

export type AttentionTone = "critical" | "warning" | "neutral" | "estimate";

/** A card for something a person must act on: severity stripe, title, key figure, details, actions. */
export function AttentionCard({ tone, title, badge, figure, children, actions, label }: {
  tone: AttentionTone;
  title: ReactNode;
  badge?: ReactNode;
  figure?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  /** Accessible name for the card (defaults to the title when it is text). */
  label?: string;
}) {
  return (
    <article className={`attn-card tone-${tone}`} aria-label={label ?? (typeof title === "string" ? title : undefined)}>
      <header className="attn-head">
        <h3 className="attn-title">{title}</h3>
        {badge}
      </header>
      {figure ? <div className="attn-figure">{figure}</div> : null}
      {children ? <div className="attn-body">{children}</div> : null}
      {actions ? <div className="attn-actions">{actions}</div> : null}
    </article>
  );
}

/** A real finite number from the API, or null (never coerced to 0). */
export function apiNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Billed against expected as two bars on one scale (the larger of the two). Drawn only when both
 * are real numbers; otherwise nothing is rendered and the caller shows the figures as text.
 */
export function CompareBar({ billed, expected, label }: { billed: unknown; expected: unknown; label: string }) {
  const b = apiNumber(billed);
  const e = apiNumber(expected);
  if (b === null || e === null) return null;
  const max = Math.max(b, e) || 1;
  return (
    <div className="compare-bar" role="img" aria-label={`${label}: billed ${b}, expected ${e}`}>
      <span className="compare-track"><span className="compare-fill is-expected" style={{ width: `${(e / max) * 100}%` }} /></span>
      <span className="compare-track"><span className={`compare-fill is-billed ${b < e ? "is-short" : ""}`} style={{ width: `${(b / max) * 100}%` }} /></span>
    </div>
  );
}

/** Heading for a page zone: title, count, one-line purpose and actions on the right. */
export function SectionHead({ title, count, sub, actions, id, level = 2 }: {
  title: ReactNode;
  count?: number;
  sub?: ReactNode;
  actions?: ReactNode;
  id?: string;
  level?: 2 | 3;
}) {
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <div className="insight-head">
      <div className="insight-head-text">
        <Heading className="insight-title" id={id}>
          {title}
          {count !== undefined ? <span className="insight-count">{count}</span> : null}
        </Heading>
        {sub ? <p className="insight-sub">{sub}</p> : null}
      </div>
      {actions ? <div className="insight-actions">{actions}</div> : null}
    </div>
  );
}
