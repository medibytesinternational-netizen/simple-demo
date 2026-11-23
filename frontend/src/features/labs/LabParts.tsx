import type { ReactNode } from "react";
import type { Lab } from "../../types";
import { Icon } from "../../components/icons";
import { Pill } from "../../components/ui";
import { AttentionCard, type AttentionTone } from "../../components/insight";
import {
  formatCollected,
  isUnreviewed,
  rangeBarModel,
  SEVERITY_LABEL,
  severityOf,
  type Comparison,
} from "./labStatus";

/** Severity badge from the result's own flag. Colour is always paired with a word. */
export function SeverityBadge({ lab }: { lab: Lab }) {
  const severity = severityOf(lab);
  if (severity === "critical") {
    return <span className="pill pill-solid-critical"><Icon name="alert" size={12} />Critical</span>;
  }
  if (severity === "high" || severity === "low" || severity === "abnormal") {
    return (
      <Pill tone="warning">
        {severity === "high" ? <span aria-hidden="true">▲</span> : severity === "low" ? <span aria-hidden="true">▼</span> : null}
        {SEVERITY_LABEL[severity]}
      </Pill>
    );
  }
  return (
    <Pill tone="neutral" title={severity === "unknown" ? "No flag was recorded with this result" : undefined}>
      {SEVERITY_LABEL[severity]}
    </Pill>
  );
}

export function ReviewState({ lab }: { lab: Lab }) {
  return isUnreviewed(lab)
    ? <Pill tone="warning" dot>Unreviewed</Pill>
    : <Pill tone="success" icon="check">Reviewed</Pill>;
}

/** The original reference text, always shown; "No range given" when the API sent none. */
export function ReferenceText({ lab }: { lab: Lab }) {
  const text = String(lab.reference_range ?? "").trim();
  return text
    ? <span className="lab-ref-text"><span className="lab-ref-label">Ref</span> {text}</span>
    : <span className="lab-ref-text is-missing">No range given</span>;
}

/**
 * Value against a two-sided numeric range, drawn only when the rules in labStatus.rangeBarModel
 * hold. Only the two supplied limits are labelled; a value far outside stops at the end with an arrow.
 */
export function RangeBar({ lab, compact }: { lab: Lab; compact?: boolean }) {
  const model = rangeBarModel(lab);
  if (!model) return null;
  const severity = severityOf(lab);
  const name = `${lab.name} ${lab.value} ${lab.unit}, flagged ${SEVERITY_LABEL[severity]}, reference ${model.low} to ${model.high}`;
  return (
    <div className={`range-bar sev-${severity} ${compact ? "is-compact" : ""}`} role="img" aria-label={name}>
      <div className="range-track" aria-hidden="true">
        <span className="range-band" />
        <span className={`range-marker ${model.beyond ? "is-beyond" : ""}`} style={{ left: `${model.position}%` }} />
        {model.beyond ? (
          <span className={`range-beyond is-${model.beyond}`} title={`Beyond the drawn scale (${model.beyond} the range)`}>
            {model.beyond === "above" ? "▶" : "◀"}
          </span>
        ) : null}
      </div>
      {compact ? null : (
        <div className="range-limits" aria-hidden="true">
          <span style={{ left: "25%" }}>{model.low}</span>
          <span style={{ left: "75%" }}>{model.high}</span>
        </div>
      )}
    </div>
  );
}

/** "Previous 2.4 · 18 Oct ▲ +0.5", only when the timeline has an earlier result for this test. */
export function PreviousResult({ comparison, compact }: { comparison: Comparison | null; compact?: boolean }) {
  if (!comparison) return null;
  const { previous, change } = comparison;
  if (compact) {
    // List rows: "was 5.1 · ▼ −1.0"; the date is in the tooltip and the accessible name.
    const when = previous.collected_at ? formatCollected(previous.collected_at) : "";
    const full = `Previous ${previous.value} ${previous.unit}${when ? ` on ${when}` : ""}${change ? `, change ${change.text}` : ""}`;
    return (
      <span className="lab-previous is-compact" title={full} aria-label={full}>
        was <span className="mono">{String(previous.value)}</span>
        {change ? <span className="lab-change">· {change.direction === "up" ? "▲ " : change.direction === "down" ? "▼ " : ""}{change.text}</span> : null}
      </span>
    );
  }
  return (
    <span className="lab-previous">
      Previous <span className="mono">{String(previous.value)} {previous.unit}</span>
      {previous.collected_at ? <> · {formatCollected(previous.collected_at)}</> : null}
      {change ? (
        <span className="lab-change">
          {change.direction === "up" ? <span aria-hidden="true">▲ </span> : change.direction === "down" ? <span aria-hidden="true">▼ </span> : null}
          {change.text}
        </span>
      ) : null}
    </span>
  );
}

const TONE: Record<string, AttentionTone> = { critical: "critical", high: "warning", low: "warning", abnormal: "warning", unknown: "neutral", normal: "neutral" };

/** An unreviewed abnormal (or unflagged) result, with its own Mark reviewed button. */
export function LabAttentionCard({ lab, comparison, reviewButton, historyButton }: {
  lab: Lab;
  comparison: Comparison | null;
  reviewButton: ReactNode;
  historyButton?: ReactNode;
}) {
  const when = formatCollected(lab.collected_at);
  return (
    <AttentionCard
      tone={TONE[severityOf(lab)]}
      title={lab.name}
      label={`${lab.name}: ${lab.value} ${lab.unit}, ${SEVERITY_LABEL[severityOf(lab)]}, unreviewed`}
      badge={<SeverityBadge lab={lab} />}
      figure={<><span className="attn-value">{lab.value}</span> <span className="attn-unit">{lab.unit}</span></>}
      actions={<>{reviewButton}{historyButton}</>}
    >
      <ReferenceText lab={lab} />
      <RangeBar lab={lab} />
      <div className="attn-meta">
        {when ? <span>Collected {when}</span> : null}
        <PreviousResult comparison={comparison} />
      </div>
    </AttentionCard>
  );
}

/** One result in the list: name, value, reference (text + safe bar), flag, review state, action. */
export function LabRow({ lab, comparison, action, history }: {
  lab: Lab;
  comparison: Comparison | null;
  action?: ReactNode;
  history?: ReactNode;
}) {
  const severity = severityOf(lab);
  const when = formatCollected(lab.collected_at);
  return (
    <li className={`lab-row sev-${severity} ${isUnreviewed(lab) ? "is-unreviewed" : "is-reviewed"}`}>
      <div className="lab-cell lab-name-cell">
        <span className="lab-name">{lab.name}</span>
        <span className="lab-sub">
          {when ? <>Collected {when}</> : null}
          {history}
        </span>
      </div>
      <div className="lab-cell lab-value-cell">
        <span className="lab-reading">{lab.value}</span> <span className="lab-unit">{lab.unit}</span>
        <PreviousResult comparison={comparison} compact />
      </div>
      <div className="lab-cell lab-ref-cell">
        <ReferenceText lab={lab} />
        <RangeBar lab={lab} compact />
      </div>
      <div className="lab-cell lab-flag-cell"><SeverityBadge lab={lab} /></div>
      <div className="lab-cell lab-state-cell"><ReviewState lab={lab} /></div>
      <div className="lab-cell lab-action-cell">{action}</div>
    </li>
  );
}
