import type { ReactNode } from "react";

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
  return (
    <>
      <div className="modal-backdrop" onClick={onClose} />
      <div className="modal" style={width ? { width: `min(${width}px, 92vw)` } : undefined}>
        <div className="modal-head">
          <div className="card-title">{title}</div>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </div>
    </>
  );
}
