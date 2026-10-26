import type { ReactNode } from "react";
import { Icon } from "../icons";

export type Tone = "neutral" | "info" | "ai" | "success" | "warning" | "critical";

/** Status pill. Colour is never the only signal: text always, dot or icon optional. */
export function Pill({ tone = "neutral", dot, icon, title, children }: { tone?: Tone; dot?: boolean; icon?: string; title?: string; children: ReactNode }) {
  return (
    <span className={`pill pill-${tone}`} title={title}>
      {dot ? <span className="pill-dot" aria-hidden="true" /> : null}
      {icon ? <Icon name={icon} size={12} /> : null}
      {children}
    </span>
  );
}

/** Small outlined fact: due time, counts, sources. */
export function MetaChip({ icon, tone, title, children }: { icon?: string; tone?: "critical" | "warning"; title?: string; children: ReactNode }) {
  return (
    <span className={`meta-chip ${tone || ""}`} title={title}>
      {icon ? <Icon name={icon} size={13} /> : null}
      {children}
    </span>
  );
}

/** Honest ratio bar. `steps` renders a segmented lifecycle instead of a continuous fill. */
export function Progress({ value, max = 100, label, tone, steps, current, showLabel = true }: {
  value: number;
  max?: number;
  label?: string;
  tone?: "accent" | "critical" | "warning" | "success";
  steps?: number;
  current?: boolean;
  showLabel?: boolean;
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, Math.round((value / max) * 100))) : 0;
  const text = label ?? `${pct}%`;
  return (
    <div className={`progress ${tone ? `tone-${tone}` : ""}`} role="progressbar" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-label={text}>
      {steps ? (
        <div className="progress-steps" aria-hidden="true">
          {Array.from({ length: steps }, (_, i) => (
            <span key={i} className={i < value ? "done" : i === value && current ? "current" : ""} />
          ))}
        </div>
      ) : (
        <div className="progress-track" aria-hidden="true"><div className="progress-fill" style={{ width: `${pct}%` }} /></div>
      )}
      {showLabel ? <span className="progress-label">{text}</span> : null}
    </div>
  );
}

export function Panel({ title, sub, count, actions, footer, padded, className, id, children }: {
  title?: ReactNode;
  sub?: ReactNode;
  count?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  padded?: boolean;
  className?: string;
  id?: string;
  children?: ReactNode;
}) {
  return (
    <section className={`panel ${className || ""}`} id={id}>
      {title || actions ? (
        <div className="panel-head">
          <div className="panel-head-text">
            {title ? <h2 className="panel-title">{title}{count !== undefined ? <span className="panel-count">{count}</span> : null}</h2> : null}
            {sub ? <p className="panel-sub">{sub}</p> : null}
          </div>
          {actions ? <div className="panel-actions">{actions}</div> : null}
        </div>
      ) : null}
      {padded ? <div className="panel-body">{children}</div> : children}
      {footer ? <div className="panel-foot">{footer}</div> : null}
    </section>
  );
}

export function Field({ label, htmlFor, required, hint, error, children }: {
  label: ReactNode;
  htmlFor?: string;
  required?: boolean;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <div className="form-field">
      <label className="field-label" htmlFor={htmlFor}>{label}{required ? <span className="req"> *</span> : null}</label>
      {children}
      {error ? <div className="field-error" role="alert">{error}</div> : hint ? <div className="field-hint">{hint}</div> : null}
    </div>
  );
}

const BANNER_ICON: Record<string, string> = { info: "info", warning: "alert", danger: "alert", success: "check", ai: "spark" };

export function Banner({ tone = "info", title, actions, icon, role, children }: {
  tone?: "info" | "warning" | "danger" | "success" | "ai";
  title?: ReactNode;
  actions?: ReactNode;
  icon?: string | false;
  role?: "status" | "alert";
  children?: ReactNode;
}) {
  const name = icon === false ? null : icon || BANNER_ICON[tone];
  return (
    <div className={`banner ${tone === "info" ? "" : tone}`} role={role}>
      {name ? <Icon name={name} size={17} /> : null}
      <div className="banner-body">
        {title ? <div className="banner-title">{title}</div> : null}
        {children}
      </div>
      {actions ? <div className="banner-actions">{actions}</div> : null}
    </div>
  );
}

export function EmptyState({ icon = "inbox", title, children, action }: { icon?: string; title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <span className="empty-icon" aria-hidden="true"><Icon name={icon} size={22} /></span>
      <div className="empty-title">{title}</div>
      {children ? <div className="empty-body">{children}</div> : null}
      {action ? <div className="empty-action">{action}</div> : null}
    </div>
  );
}

/** Loading placeholders shaped like the content they stand in for. */
export function Skeleton({ variant = "lines", count = 3 }: { variant?: "lines" | "rows" | "table"; count?: number }) {
  if (variant === "rows") {
    return (
      <div className="rows" aria-busy="true" aria-label="Loading">
        {Array.from({ length: count }, (_, i) => (
          <div className="sk-row" key={i}>
            <span className="sk sk-lead" />
            <span className="sk-lines"><span className="sk" style={{ width: `${70 - i * 8}%` }} /><span className="sk" style={{ width: "40%", height: 10 }} /></span>
            <span className="sk" />
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="skeleton-rows" aria-busy="true" aria-label="Loading">
      {Array.from({ length: count }, (_, i) => <span key={i} />)}
    </div>
  );
}

export type StepState = "done" | "current" | "todo";

export function Stepper({ steps, label = "Progress" }: { steps: { label: string; state: StepState }[]; label?: string }) {
  return (
    <ol className="stepper" aria-label={label}>
      {steps.map((step, i) => (
        <li key={step.label} style={{ display: "contents" }}>
          {i > 0 ? <span className="step-line" aria-hidden="true" /> : null}
          <span className={`step ${step.state}`} aria-current={step.state === "current" ? "step" : undefined}>
            <span className="step-num">{step.state === "done" ? <Icon name="check" size={13} /> : i + 1}</span>
            {step.label}
            <span className="sr-only">{step.state === "done" ? " (done)" : step.state === "current" ? " (current)" : ""}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Native details/summary: zero-JS disclosure for secondary explanations. */
export function Disclosure({ title, defaultOpen, children }: { title: ReactNode; defaultOpen?: boolean; children: ReactNode }) {
  return (
    <details className="disclosure" open={defaultOpen}>
      <summary><Icon name="chevron" size={15} />{title}</summary>
      <div className="disclosure-body">{children}</div>
    </details>
  );
}
