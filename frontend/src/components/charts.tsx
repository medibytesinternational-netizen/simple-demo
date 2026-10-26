import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export type BarItem = {
  key: string;
  label: string;
  value: number;
  note?: ReactNode;
  to?: string;
  onSelect?: () => void;
  selected?: boolean;
  tone?: "accent" | "critical" | "warning" | "neutral";
};

/**
 * Compact horizontal bar list. Exact values are always visible, the scale
 * starts at zero, and every row is a real link or button. The bars are a
 * visual aid, not the only way to read the number.
 */
export function BarList({ items, max, unit = "", scope, empty, ariaLabel, className = "" }: {
  items: BarItem[];
  max?: number;
  unit?: string;
  scope?: ReactNode;
  empty?: ReactNode;
  ariaLabel?: string;
  className?: string;
}) {
  if (!items.length) {
    return <div className="chart-empty">{empty || "No data to show."}</div>;
  }
  const top = Math.max(1, max ?? Math.max(...items.map((item) => item.value)));
  return (
    <div className={`chart chart-bars ${className}`}>
      {scope ? <p className="chart-scope">{scope}</p> : null}
      <ul className="bar-list" aria-label={ariaLabel}>
        {items.map((item) => {
          const pct = Math.max(0, Math.min(100, (item.value / top) * 100));
          const body = (
            <>
              <span className="bar-head">
                <span className="bar-label">{item.label}</span>
                <span className="bar-value">{item.value}{unit ? <span className="bar-unit"> {unit}</span> : null}</span>
              </span>
              <span className="bar-track" aria-hidden="true">
                <span className={`bar-fill tone-${item.tone || "accent"}`} style={{ width: `${pct}%` }} />
              </span>
              {item.note ? <span className="bar-note">{item.note}</span> : null}
            </>
          );
          const described = [item.label, `${item.value}${unit ? ` ${unit}` : ""}`, item.note].filter(Boolean).join(". ");
          return (
            <li key={item.key}>
              {item.to ? (
                <Link to={item.to} className={`bar-row ${item.selected ? "is-selected" : ""}`} aria-label={described}>
                  {body}
                </Link>
              ) : item.onSelect ? (
                <button type="button" className={`bar-row ${item.selected ? "is-selected" : ""}`} aria-pressed={item.selected} onClick={item.onSelect}>
                  {body}
                </button>
              ) : (
                <div className={`bar-row ${item.selected ? "is-selected" : ""}`}>{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export type ChartPoint = { at: string; value: number; label?: string };

/**
 * One real clinical series. A single reading is drawn as a labelled point and
 * explicitly says that there is not enough history for a trend. No values are
 * inferred, interpolated or rounded.
 */
export function TrendChart({ points, unit, title, reference, height = 128 }: {
  points: ChartPoint[];
  unit: string;
  title: string;
  reference?: { low?: number; high?: number; text?: string };
  height?: number;
}) {
  const valid = points.filter((p) => Number.isFinite(p.value));
  if (!valid.length) {
    return <div className="chart-empty">No readings recorded for {title.toLowerCase()}.</div>;
  }
  const width = 320;
  const pad = { left: 38, right: 12, top: 14, bottom: 24 };
  const values = valid.map((p) => p.value);
  const refLow = reference?.low;
  const refHigh = reference?.high;
  const domainValues = [...values, ...(refLow !== undefined ? [refLow] : []), ...(refHigh !== undefined ? [refHigh] : [])];
  let min = Math.min(...domainValues);
  let max = Math.max(...domainValues);
  if (min === max) { min = min * 0.9; max = max * 1.1 || 1; }
  const span = max - min;
  min = Math.max(0, min - span * 0.15);
  max = max + span * 0.15;
  const times = valid.map((p) => Date.parse(p.at)).filter(Number.isFinite);
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const x = (p: ChartPoint, i: number) => {
    const t = Date.parse(p.at);
    if (!Number.isFinite(t) || tMin === tMax) return pad.left + ((width - pad.left - pad.right) * (valid.length === 1 ? 0.5 : i / (valid.length - 1)));
    return pad.left + ((t - tMin) / (tMax - tMin)) * (width - pad.left - pad.right);
  };
  const y = (value: number) => pad.top + (1 - (value - min) / (max - min)) * (height - pad.top - pad.bottom);
  const path = valid.map((p, i) => `${i ? "L" : "M"}${x(p, i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const first = valid[0];
  const last = valid[valid.length - 1];
  const clock = (at: string) => {
    const date = new Date(at);
    return Number.isNaN(date.getTime()) ? at : date.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  };
  const summary = `${title}: ${valid.map((p) => `${p.value} ${unit} at ${clock(p.at)}`).join("; ")}. ${reference?.text ? `Reference ${reference.text}.` : ""} ${valid.length < 2 ? "Not enough history for a trend." : ""}`.trim();

  return (
    <figure className="chart chart-trend">
      <figcaption className="chart-caption">{title}</figcaption>
      {valid.length < 2 ? <p className="chart-note">One reading only — not enough history for a trend.</p> : null}
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={summary} preserveAspectRatio="none">
        <line x1={pad.left} x2={width - pad.right} y1={y(max)} y2={y(max)} className="trend-grid" />
        <line x1={pad.left} x2={width - pad.right} y1={y(min)} y2={y(min)} className="trend-grid" />
        {refLow !== undefined && refHigh !== undefined ? (
          <rect x={pad.left} y={y(refHigh)} width={width - pad.left - pad.right} height={Math.max(1, y(refLow) - y(refHigh))} className="trend-band" />
        ) : null}
        {valid.length > 1 ? <path d={path} className="trend-line" /> : null}
        {valid.map((p, i) => (
          <g key={`${p.at}-${i}`}>
            <circle cx={x(p, i)} cy={y(p.value)} r={valid.length === 1 ? 5 : 3.5} className="trend-point" />
            <text x={x(p, i)} y={y(p.value) - 8} textAnchor="middle" className="trend-value">{p.value}</text>
          </g>
        ))}
        <text x={pad.left} y={height - 7} textAnchor="start" className="trend-axis">{clock(first.at)}</text>
        {valid.length > 1 ? <text x={width - pad.right} y={height - 7} textAnchor="end" className="trend-axis">{clock(last.at)}</text> : null}
        <text x={pad.left - 5} y={y(max) + 3} textAnchor="end" className="trend-axis">{max.toFixed(1)}</text>
        <text x={pad.left - 5} y={y(min) + 3} textAnchor="end" className="trend-axis">{min.toFixed(1)}</text>
      </svg>
      <p className="chart-scope">Unit: {unit}. {reference?.text ? `Reference: ${reference.text}.` : "Reference range not supplied."} Times shown in the demo clock.</p>
      <table className="sr-only">
        <caption>{title}</caption>
        <thead><tr><th>Recorded</th><th>Value ({unit})</th></tr></thead>
        <tbody>{valid.map((p, i) => <tr key={i}><td>{clock(p.at)}</td><td>{p.value}</td></tr>)}</tbody>
      </table>
    </figure>
  );
}

/**
 * A single lab value against its supplied reference range. The range string is
 * parsed only when it is a simple numeric interval; otherwise the exact text
 * is shown without a drawn band.
 */
export function ReferenceValue({ name, value, unit, reference, flag, collectedAt }: {
  name: string;
  value: string | number;
  unit: string;
  reference: string;
  flag?: string;
  collectedAt?: string;
}) {
  const numeric = typeof value === "number" ? value : Number.parseFloat(String(value).replace(/,/g, ""));
  const parsed = parseRange(reference);
  const abnormal = flag === "high" || flag === "low" || flag === "critical";
  const relation = Number.isFinite(numeric) && parsed
    ? parsed.low !== undefined && numeric < parsed.low ? "below range"
      : parsed.high !== undefined && numeric > parsed.high ? "above range"
        : "within range"
    : null;
  let domainMin = 0;
  let domainMax = 1;
  let lowPct = 0;
  let highPct = 100;
  if (Number.isFinite(numeric) && parsed) {
    const candidates = [numeric, parsed.low, parsed.high].filter((n): n is number => n !== undefined);
    domainMax = Math.max(...candidates) * 1.25 || 1;
    if (parsed.high !== undefined && parsed.low === undefined) domainMax = Math.max(parsed.high * 1.25, numeric * 1.1);
    if (parsed.low !== undefined) lowPct = Math.max(0, Math.min(100, (parsed.low / domainMax) * 100));
    if (parsed.high !== undefined) highPct = Math.max(0, Math.min(100, (parsed.high / domainMax) * 100));
  }
  const markerPct = Number.isFinite(numeric) ? Math.max(0, Math.min(100, (numeric / domainMax) * 100)) : null;
  const when = collectedAt ? new Date(collectedAt).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : null;

  return (
    <div className={`ref-value ${abnormal ? "is-abnormal" : ""}`}>
      <div className="ref-head">
        <span className="ref-name">{name}</span>
        <span className="ref-reading">{value} <span className="ref-unit">{unit}</span></span>
      </div>
      {parsed && markerPct !== null ? (
        <div className="ref-scale" role="img" aria-label={`${name}: ${value} ${unit}; reference ${reference}${relation ? `; ${relation}` : ""}`}>
          <span className="ref-track" aria-hidden="true">
            <span className="ref-band" style={{ left: `${lowPct}%`, width: `${Math.max(0, highPct - lowPct)}%` }} />
            <span className={`ref-marker ${abnormal ? "is-out" : ""}`} style={{ left: `${markerPct}%` }} />
          </span>
          <span className="ref-bounds" aria-hidden="true"><span>{domainMin}</span><span>{domainMax.toFixed(domainMax < 10 ? 1 : 0)}</span></span>
        </div>
      ) : null}
      <div className="ref-meta">
        <span>Reference {reference}</span>
        {relation ? <span className={abnormal ? "ref-flag" : ""}>{relation}</span> : null}
        {when ? <span>{when}</span> : null}
      </div>
    </div>
  );
}

export function parseRange(text: string): { low?: number; high?: number } | null {
  if (!text) return null;
  const cleaned = text.replace(/\u2013|\u2014/g, "-").replace(/\s+/g, " ").trim();
  const both = cleaned.match(/^(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)$/);
  if (both) return { low: Number(both[1]), high: Number(both[2]) };
  const lowOnly = cleaned.match(/^>\s*(-?\d+(?:\.\d+)?)$/);
  if (lowOnly) return { low: Number(lowOnly[1]) };
  const highOnly = cleaned.match(/^<\s*(-?\d+(?:\.\d+)?)$/);
  if (highOnly) return { high: Number(highOnly[1]) };
  return null;
}

export type PillBar = {
  key: string;
  label: string;
  /** Exact value shown under the bar and in the accessible name. */
  valueText: string;
  /** Filled share of the bar, 0 to 1. */
  share: number;
  tone?: "accent" | "deep" | "soft" | "critical" | "warning";
  /** Short text announced with the bar, e.g. the reference range. */
  detail?: string;
};

/**
 * Vertical rounded bars, one per category. The filled part is the real share;
 * the hatched part is what remains (free beds, headroom to a limit). Exact
 * values are printed under every bar, so the chart is never the only source.
 */
export function PillBars({ items, ariaLabel, highlight, markerAt, markerLabel }: {
  items: PillBar[];
  ariaLabel: string;
  highlight?: string;
  /** Optional dashed reference line across every bar, as a share of the height. */
  markerAt?: number;
  markerLabel?: string;
}) {
  if (!items.length) return <div className="chart-empty">No data to show.</div>;
  return (
    <ul className="pill-bars" aria-label={ariaLabel}>
      {items.map((item) => {
        const share = Math.max(0, Math.min(1, item.share));
        return (
          <li key={item.key} className={`pill-bar ${highlight === item.key ? "is-highlight" : ""}`}
            aria-label={[item.label, item.valueText, item.detail].filter(Boolean).join(". ")}>
            <span className="pill-bar-track" aria-hidden="true">
              {highlight === item.key ? <span className="pill-bar-tip">{item.valueText}</span> : null}
              {markerAt !== undefined ? <span className="pill-bar-marker" style={{ bottom: `${markerAt * 100}%` }} title={markerLabel} /> : null}
              <span className={`pill-bar-fill tone-${item.tone || "accent"}`} style={{ height: `${Math.max(share * 100, share > 0 ? 14 : 0)}%` }} />
            </span>
            <span className="pill-bar-value" aria-hidden="true">{item.valueText}</span>
            <span className="pill-bar-label" aria-hidden="true">{item.label}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** Semicircle gauge for one real proportion, with the exact figure in the middle. */
export function HalfGauge({ value, max, label, caption, segments }: {
  value: number;
  max: number;
  label: string;
  caption: string;
  /** Optional legend rows; the gauge itself draws value / max. */
  segments?: { key: string; label: string; value: number; tone: "fill" | "deep" | "hatch" }[];
}) {
  const share = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  const r = 80;
  const length = Math.PI * r;
  const arc = `M 20 100 A ${r} ${r} 0 0 1 180 100`;
  return (
    <figure className="half-gauge" aria-label={`${label}: ${caption}`}>
      <div className="gauge-dial">
      <svg viewBox="0 0 200 112" role="img" aria-hidden="true">
        <defs>
          <pattern id="gauge-hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="7" height="7" className="gauge-hatch-bg" />
            <line x1="0" y1="0" x2="0" y2="7" className="gauge-hatch-line" strokeWidth="3.2" />
          </pattern>
          <linearGradient id="gauge-fill" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="#153e75" />
            <stop offset="100%" stopColor="#2563eb" />
          </linearGradient>
        </defs>
        <path d={arc} className="gauge-track" stroke="url(#gauge-hatch)" strokeWidth="30" fill="none" strokeLinecap="round" />
        <path d={arc} className="gauge-fill" stroke="url(#gauge-fill)" strokeWidth="30" fill="none" strokeLinecap="round"
          strokeDasharray={`${share * length} ${length}`} style={{ opacity: share > 0 ? 1 : 0 }} />
      </svg>
        <span className="gauge-value" aria-hidden="true">{Math.round(share * 100)}%</span>
      </div>
      <figcaption className="gauge-caption">{caption}</figcaption>
      {segments?.length ? (
        <ul className="gauge-legend">
          {segments.map((s) => (
            <li key={s.key}><span className={`gauge-key tone-${s.tone}`} aria-hidden="true" />{s.label} <strong>{s.value}</strong></li>
          ))}
        </ul>
      ) : null}
    </figure>
  );
}
