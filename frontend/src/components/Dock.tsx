import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { COUNT_TONE, DOCK_ITEMS, type CountKey } from "./modules";
import { Icon } from "./icons";
import { Launchpad } from "./Launchpad";

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
 * macOS-style dock: the main navigation. It sits in its own strip under the
 * paper canvas (not on top of it), so it never covers content. The last tile
 * opens the Launchpad with every module; Ctrl/Cmd+K opens it from anywhere.
 */
export function Dock({ counts, launchpadOpen, setLaunchpadOpen }: {
  counts: Record<CountKey, number>;
  launchpadOpen: boolean;
  setLaunchpadOpen: (open: boolean) => void;
}) {
  const location = useLocation();
  const tab = new URLSearchParams(location.search).get("tab");
  const [scales, setScales] = useState<number[]>([]);
  const [focus, setFocus] = useState(0);
  const refs = useRef<(HTMLElement | null)[]>([]);
  const magnify = useMagnify();
  const total = DOCK_ITEMS.length + 1;
  const launcherIndex = DOCK_ITEMS.length;

  // Any route change closes the launchpad.
  useEffect(() => { setLaunchpadOpen(false); }, [location.pathname, location.search, setLaunchpadOpen]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setLaunchpadOpen(!launchpadOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [launchpadOpen, setLaunchpadOpen]);

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
      <nav aria-label="Main">
        <ul className={`dock glass ${magnify ? "can-magnify" : ""}`} onPointerMove={onMove} onPointerLeave={() => setScales([])} onKeyDown={onKey}>
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
                  {count ? <span className={`dock-badge ${COUNT_TONE[item.count!]}`} aria-hidden="true">{count}</span> : null}
                </Link>
              </li>
            );
          })}
          <li aria-hidden="true"><span className="dock-sep" /></li>
          <li>
            <button type="button" ref={(el) => { refs.current[launcherIndex] = el; }} className={`dock-item ${launchpadOpen ? "active" : ""}`}
              aria-haspopup="dialog" aria-expanded={launchpadOpen} aria-label="All modules (Ctrl+K)"
              tabIndex={launcherIndex === focus ? 0 : -1} onFocus={() => setFocus(launcherIndex)} onClick={() => setLaunchpadOpen(!launchpadOpen)}
              style={{ transform: `scale(${scales[launcherIndex] || 1})` }}>
              <span className="dock-icon"><Icon name="launcher" size={21} /></span>
              <span className="dock-label">All modules</span>
            </button>
          </li>
        </ul>
      </nav>
      {launchpadOpen ? createPortal(<Launchpad counts={counts} onClose={() => setLaunchpadOpen(false)} />, document.body) : null}
    </div>
  );
}
