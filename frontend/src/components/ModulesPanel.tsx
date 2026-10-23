import { useEffect, useRef } from "react";
import { Link, useLocation } from "react-router-dom";
import { NAV_GROUPS, findActive } from "./modules";
import { Icon } from "./icons";

type Counts = { alerts: number; overdue: number };

/**
 * Every module that the left navigation used to list, grouped the same way, opened from the
 * dock's Modules button. Choosing a module, pressing Escape or clicking outside closes it.
 */
export function ModulesPanel({ counts, onClose }: { counts: Counts; onClose: (returnFocus: boolean) => void }) {
  const location = useLocation();
  const active = findActive(location.pathname, new URLSearchParams(location.search).get("tab"));
  const panel = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    (panel.current?.querySelector<HTMLElement>(".nav-item.active") || panel.current?.querySelector<HTMLElement>("a[href]"))?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(true); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="modules-backdrop" onClick={() => onClose(true)} aria-hidden="true" />
      <div className="modules-panel" id="modules-panel" role="dialog" aria-label="All modules" ref={panel}>
        <div className="modules-panel-head">
          <span className="modules-panel-title">All modules</span>
          <button type="button" className="icon-btn" onClick={() => onClose(true)} aria-label="Close modules"><Icon name="close" size={18} /></button>
        </div>
        <div className="modules-panel-body">
          {NAV_GROUPS.map((group) => (
            <section key={group.id} className="nav-group modules-group" aria-label={group.title}>
              <div className="nav-group-title static">{group.title}</div>
              <ul className="nav-items">
                {group.items.map((item) => {
                  const isActive = item.id === active?.id;
                  const count = item.count ? counts[item.count] : 0;
                  return (
                    <li key={item.id}>
                      <Link to={item.to} className={`nav-item ${isActive ? "active" : ""}`} aria-current={isActive ? "page" : undefined}
                        title={item.hint} onClick={() => onClose(false)}>
                        <Icon name={item.icon} size={18} className="nav-icon" />
                        <span className="nav-label">{item.label}</span>
                        {count ? <span className={`nav-count ${item.count === "alerts" ? "critical" : "warning"}`} aria-label={`${count} open`}>{count}</span> : null}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </>
  );
}
