import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { LAUNCHER_GROUPS } from "./modules";
import type { ModuleLink } from "./modules";
import { Icon } from "./icons";

// Searchable dialog listing every module; opened from the left navigation.
export function Launcher({ onClose, onAudit }: { onClose: (returnFocus?: boolean) => void; onAudit: () => void }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [query, setQuery] = useState("");
  const panel = useRef<HTMLDivElement | null>(null);
  const search = useRef<HTMLInputElement | null>(null);
  const current = location.pathname + location.search;

  useEffect(() => {
    search.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab" && panel.current) {
        // keep focus inside the dialog while it is open
        const focusable = panel.current.querySelectorAll<HTMLElement>("input, button, a[href]");
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return LAUNCHER_GROUPS;
    return LAUNCHER_GROUPS.map((group) => ({
      ...group,
      items: group.items.filter((item) => `${item.label} ${item.code || ""}`.toLowerCase().includes(q)),
    })).filter((group) => group.items.length);
  }, [query]);

  function open(item: ModuleLink) {
    if (item.action === "audit") {
      onClose(false);
      onAudit();
      return;
    }
    onClose(false);
    navigate(item.to);
  }

  return (
    <>
      <div className="launcher-backdrop" onClick={() => onClose()} />
      <div className="launcher" role="dialog" aria-modal="true" aria-label="All modules" ref={panel}>
        <div className="launcher-head">
          <div className="launcher-search">
            <Icon name="search" size={16} />
            <input
              ref={search}
              className="launcher-input"
              placeholder="Search modules"
              aria-label="Search modules"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => onClose()} aria-label="Close modules">
            <Icon name="close" size={16} />
          </button>
        </div>
        <div className="launcher-body">
          {groups.map((group) => (
            <section key={group.title} className="launcher-group">
              <div className="launcher-group-title">{group.title}</div>
              <div className="launcher-grid">
                {group.items.map((item) => {
                  const active = item.to && (item.to === current || (!item.to.includes("?") && item.to === location.pathname));
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={`launcher-item ${active ? "active" : ""}`}
                      onClick={() => open(item)}
                      aria-current={active ? "page" : undefined}
                    >
                      <span className="launcher-icon"><Icon name={item.icon} size={18} /></span>
                      <span className="launcher-text">
                        <span className="launcher-label">{item.label}</span>
                        {item.code ? <span className="launcher-code">{item.code}</span> : null}
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
          {!groups.length ? <div className="empty">No module matches “{query}”.</div> : null}
        </div>
      </div>
    </>
  );
}
