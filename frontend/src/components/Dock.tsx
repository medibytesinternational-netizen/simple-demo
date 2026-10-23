import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { DOCK_ITEMS } from "./modules";
import { Icon } from "./icons";
import { ModulesPanel } from "./ModulesPanel";

const MAX_SCALE = 0.16;
const REACH = 100;

function useMagnify() {
  const [ok, setOk] = useState(false);
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)");
    const update = () => setOk(!reduce.matches && fine.matches);
    update();
    reduce.addEventListener("change", update);
    fine.addEventListener("change", update);
    return () => { reduce.removeEventListener("change", update); fine.removeEventListener("change", update); };
  }, []);
  return ok;
}

/**
 * Floating shortcut bar. It sits in its own reserved strip under the scrolling
 * page (not on top of it), so it never covers content, forms or buttons.
 */
export function Dock({ counts }: { counts: { alerts: number; overdue: number } }) {
  const location = useLocation();
  const tab = new URLSearchParams(location.search).get("tab");
  const [scales, setScales] = useState<number[]>([]);
  const [focus, setFocus] = useState(0);
  const refs = useRef<(HTMLElement | null)[]>([]);
  const magnify = useMagnify();
  // The five shortcuts plus the Modules button, which opens every module.
  const total = DOCK_ITEMS.length + 1;
  const [modulesOpen, setModulesOpen] = useState(false);
  const modulesIndex = DOCK_ITEMS.length;
  const closeModules = useCallback((returnFocus: boolean) => {
    setModulesOpen(false);
    if (returnFocus) refs.current[modulesIndex]?.focus();
  }, [modulesIndex]);

  // Any route change (from the panel or elsewhere) closes the panel.
  useEffect(() => { setModulesOpen(false); }, [location.pathname, location.search]);

  const onMove = (e: ReactPointerEvent) => {
    if (!magnify) return;
    setScales(refs.current.map((el) => {
      if (!el) return 1;
      const r = el.getBoundingClientRect();
      return 1 + MAX_SCALE * Math.max(0, 1 - Math.abs(e.clientX - (r.left + r.width / 2)) / REACH);
    }));
  };
  const onKey = (e: ReactKeyboardEvent) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = (focus + step + total) % total;
    setFocus(next);
    refs.current[next]?.focus();
  };

  return (
    <div className="dock-strip">
      <nav aria-label="Shortcuts">
        <ul className={`dock ${magnify ? "can-magnify" : ""}`} onPointerMove={onMove} onPointerLeave={() => setScales([])} onKeyDown={onKey}>
          {DOCK_ITEMS.map((item, i) => {
            const active = item.match(location.pathname, tab);
            const count = item.count ? counts[item.count] : 0;
            return (
              <li key={item.id}>
                <Link ref={(el) => { refs.current[i] = el; }} to={item.to} className={`dock-item ${active ? "active" : ""}`}
                  aria-current={active ? "page" : undefined} aria-label={count ? `${item.label}, ${count}` : item.label}
                  tabIndex={i === focus ? 0 : -1} onFocus={() => setFocus(i)} style={{ transform: `scale(${scales[i] || 1})` }}>
                  <span className="dock-icon"><Icon name={item.icon} size={21} /></span>
                  <span className="dock-label">{item.label}</span>
                  {count ? <span className={`dock-badge ${item.count === "alerts" ? "critical" : "warning"}`} aria-hidden="true">{count}</span> : null}
                </Link>
              </li>
            );
          })}
          <li>
            <button type="button" ref={(el) => { refs.current[modulesIndex] = el; }} className={`dock-item ${modulesOpen ? "active" : ""}`}
              aria-haspopup="dialog" aria-expanded={modulesOpen} aria-controls="modules-panel" aria-label="Modules: all modules"
              tabIndex={modulesIndex === focus ? 0 : -1} onFocus={() => setFocus(modulesIndex)} onClick={() => (modulesOpen ? closeModules(true) : setModulesOpen(true))}
              style={{ transform: `scale(${scales[modulesIndex] || 1})` }}>
              <span className="dock-icon"><Icon name="launcher" size={21} /></span>
              <span className="dock-label">Modules</span>
            </button>
          </li>
        </ul>
      </nav>
      {modulesOpen ? <ModulesPanel counts={counts} onClose={closeModules} /> : null}
    </div>
  );
}
