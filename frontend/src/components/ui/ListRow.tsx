import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon } from "../icons";

type Common = {
  lead?: ReactNode;
  icon?: string;
  tone?: "critical" | "warning" | "info" | "ai" | "success" | "neutral";
  title: ReactNode;
  meta?: ReactNode;
  body?: ReactNode;
  chips?: ReactNode;
  side?: ReactNode;
  expand?: ReactNode;
  selected?: boolean;
  muted?: boolean;
  chevron?: boolean;
  className?: string;
  /** A link or button row. Leave both unset when the row holds its own buttons. */
  to?: string;
  onClick?: () => void;
};

/**
 * Sundays-style card row: leading tile, title and meta, chips, and a right-hand
 * side for progress or actions. Tone shows in the tile tint and pills only.
 */
export function ListRow(props: Common) {
  const { lead, icon, tone, title, meta, body, chips, side, expand, selected, muted, chevron, className } = props;
  const cls = `lrow ${tone ? `tone-${tone}` : ""} ${selected ? "selected" : ""} ${muted ? "muted-row" : ""} ${className || ""}`;
  const inner = (
    <>
      {lead ?? (icon ? <span className="lrow-lead" aria-hidden="true"><Icon name={icon} size={18} /></span> : <span />)}
      <span className="lrow-main">
        <span className="lrow-title">{title}</span>
        {meta ? <span className="lrow-meta">{meta}</span> : null}
        {body ? <span className="lrow-body">{body}</span> : null}
        {chips ? <span className="lrow-chips">{chips}</span> : null}
      </span>
      {side || chevron ? (
        <span className="lrow-side">
          {side}
          {chevron ? <Icon name="chevron" size={16} className="lrow-chev" /> : null}
        </span>
      ) : <span />}
      {expand ? <div className="lrow-expand">{expand}</div> : null}
    </>
  );
  if (props.to) return <Link to={props.to} className={cls} aria-current={selected ? "true" : undefined}>{inner}</Link>;
  if (props.onClick) return <button type="button" className={cls} onClick={props.onClick} aria-pressed={selected}>{inner}</button>;
  return <div className={cls}>{inner}</div>;
}
