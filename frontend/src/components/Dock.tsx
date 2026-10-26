import { Fragment, useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { COUNT_TONE, HOSPITAL_DOCK, PATIENT_DOCK, isPatientRoute, type CountKey, type DockItem } from "./modules";
import { Icon } from "./icons";

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

// Leaves the patient's record for the hospital-wide pages.
const BACK_TO_HOSPITAL: DockItem = { id: "hospital", label: "Hospital", to: "/dashboard", icon: "back", match: () => false };

const COUNT_SCOPE: Record<CountKey, (n: number) => string> = {
  alerts: (n) => `${n} open alert${n === 1 ? "" : "s"} for the current patient`,
  overdue: (n) => `${n} overdue task${n === 1 ? "" : "s"} for the current patient`,
  documents: (n) => `${n} report${n === 1 ? "" : "s"} awaiting confirmation`,
  labs: (n) => `${n} unreviewed lab result${n === 1 ? "" : "s"}`,
};

/**
 * macOS-style dock: the main navigation. It sits in its own strip under the
 * paper canvas (not on top of it), so it never covers content. It shows the
 * hospital pages, or the open patient's tabs; on phones it scrolls sideways.
 */
export function Dock({ counts }: { counts: Record<CountKey, number> }) {
  const location = useLocation();
  const tab = new URLSearchParams(location.search).get("tab");
  const [scales, setScales] = useState<number[]>([]);
  const [focus, setFocus] = useState(0);
  const refs = useRef<(HTMLElement | null)[]>([]);
  const magnify = useMagnify();
  const patientMode = isPatientRoute(location.pathname);
  const modeItems = patientMode ? PATIENT_DOCK : HOSPITAL_DOCK;
  const items = [...(patientMode ? [BACK_TO_HOSPITAL] : []), ...modeItems];
  const total = items.length;

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
      <nav aria-label={patientMode ? "Patient record" : "Hospital"}>
        <ul key={patientMode ? "patient" : "hospital"} className={`dock dock-${patientMode ? "patient" : "hospital"} ${magnify ? "can-magnify" : ""}`} onPointerMove={onMove} onPointerLeave={() => setScales([])} onKeyDown={onKey}>
          {items.map((item, i) => {
            const active = item.match(location.pathname, tab);
            const count = item.count ? counts[item.count] : 0;
            const scope = item.count && count ? COUNT_SCOPE[item.count](count) : "";
            return (
              <Fragment key={item.id}>
              <li className={item.optional ? "dock-optional" : undefined}>
                <Link ref={(el) => { refs.current[i] = el; }} to={item.to} className={`dock-item ${active ? "active" : ""} ${item.optional ? "dock-optional" : ""} ${item === BACK_TO_HOSPITAL ? "dock-back" : ""}`}
                  aria-current={active ? "page" : undefined} aria-label={item === BACK_TO_HOSPITAL ? "Back to hospital dashboard" : scope ? `${item.label}. ${scope}` : item.label}
                  title={item === BACK_TO_HOSPITAL ? "Back to hospital dashboard" : scope || item.label}
                  tabIndex={i === focus ? 0 : -1} onFocus={() => setFocus(i)}>
                  <span className="dock-icon" style={{ transform: scales[i] && scales[i] !== 1 ? `translateY(-3px) scale(${scales[i]})` : undefined }}><Icon name={item.icon} size={21} /></span>
                  <span className="dock-label">{item.label}</span>
                  {count ? <span className={`dock-badge ${COUNT_TONE[item.count!]}`} aria-hidden="true">{count}</span> : null}
                </Link>
              </li>
              {item === BACK_TO_HOSPITAL ? <li aria-hidden="true"><span className="dock-sep" /></li> : null}
              </Fragment>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
