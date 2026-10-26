import { useId, type ReactNode } from "react";
import { Icon } from "./icons";
import { useDialog } from "./ui/useDialog";

export function Modal({
  title,
  onClose,
  children,
  footer,
  width,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  const ref = useDialog<HTMLDivElement>(onClose, { initialFocus: ".modal-body input, .modal-body select, .modal-body textarea" });
  const titleId = useId();
  return (
    <>
      <div className="modal-backdrop" onClick={onClose} />
      <div ref={ref} className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        style={width ? { width: `min(${width}px, 92vw)` } : undefined}>
        <div className="modal-head">
          <h2 className="modal-title" id={titleId}>{title}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
            <Icon name="close" size={18} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </div>
    </>
  );
}
