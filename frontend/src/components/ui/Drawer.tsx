import { useId, type ReactNode } from "react";
import { Icon } from "../icons";
import { useDialog } from "./useDialog";

/** Side sheet for details that keep the page in view (evidence, patient details). */
export function Drawer({ title, sub, leading, onClose, wide, tabs, footer, children }: {
  title: ReactNode;
  sub?: ReactNode;
  leading?: ReactNode;
  onClose: () => void;
  wide?: boolean;
  tabs?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}) {
  const ref = useDialog<HTMLElement>(onClose, { initialFocus: ".drawer-close" });
  const titleId = useId();
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside ref={ref} className={`drawer ${wide ? "drawer-wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <div className="drawer-head">
          <div className="flex items-center gap-3" style={{ minWidth: 0 }}>
            {leading}
            <div style={{ minWidth: 0 }}>
              <h2 className="drawer-title" id={titleId}>{title}</h2>
              {sub ? <div className="drawer-sub">{sub}</div> : null}
            </div>
          </div>
          <button type="button" className="icon-btn drawer-close" onClick={onClose} aria-label="Close">
            <Icon name="close" size={18} />
          </button>
        </div>
        {tabs}
        <div className="drawer-body">{children}</div>
        {footer ? <div className="drawer-foot">{footer}</div> : null}
      </aside>
    </>
  );
}
