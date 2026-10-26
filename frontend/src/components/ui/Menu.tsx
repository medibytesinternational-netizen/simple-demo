import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Icon } from "../icons";

/**
 * Button plus popover (Filter, Sort, More). Escape and outside clicks close it
 * and focus returns to the trigger.
 */
export function Menu({ label, icon, badge, align = "left", buttonClass = "btn btn-sm", ariaLabel, children }: {
  label?: ReactNode;
  icon?: string;
  badge?: number;
  align?: "left" | "right";
  buttonClass?: string;
  ariaLabel?: string;
  children: ReactNode | ((close: () => void) => ReactNode);
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); trigger.current?.focus(); } };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    wrap.current?.querySelector<HTMLElement>(".menu button, .menu input, .menu select")?.focus();
    return () => { document.removeEventListener("pointerdown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const close = () => { setOpen(false); trigger.current?.focus(); };
  return (
    <div className="menu-wrap" ref={wrap}>
      <button ref={trigger} type="button" className={buttonClass} aria-haspopup="true" aria-expanded={open} aria-controls={open ? id : undefined}
        aria-label={ariaLabel} onClick={() => setOpen((v) => !v)}>
        {icon ? <Icon name={icon} size={15} /> : null}
        {label}
        {badge ? <span className="tab-count neutral">{badge}</span> : null}
      </button>
      {open ? (
        <div className={`menu ${align === "right" ? "align-right" : ""}`} id={id}>
          {typeof children === "function" ? children(close) : children}
        </div>
      ) : null}
    </div>
  );
}

export function MenuItem({ onSelect, checked, checkbox, danger, disabled, title, icon, children }: {
  onSelect: () => void;
  checked?: boolean;
  /** An on/off option (menuitemcheckbox) rather than one choice of several. */
  checkbox?: boolean;
  danger?: boolean;
  disabled?: boolean;
  title?: string;
  icon?: string;
  children: ReactNode;
}) {
  return (
    <button type="button" className={`menu-item ${danger ? "danger" : ""}`} role={checked === undefined ? "menuitem" : checkbox ? "menuitemcheckbox" : "menuitemradio"}
      aria-checked={checked} disabled={disabled} title={title} onClick={onSelect}>
      {icon ? <Icon name={icon} size={15} /> : checked !== undefined ? <span style={{ width: 15, display: "inline-grid" }}>{checked ? <Icon name="check" size={15} /> : null}</span> : null}
      {children}
    </button>
  );
}
