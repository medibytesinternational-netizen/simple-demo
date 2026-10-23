import { NavLink, useLocation } from "react-router-dom";
import { FLOW_STEPS, MORE_LINKS } from "./modules";
import { Icon } from "./icons";

/** 240px left navigation: the eight demo screens in order, then the remaining modules. */
export function SideNav({ counts, onAudit, onLauncher }: { counts: { alerts: number }; onAudit: () => void; onLauncher: () => void }) {
  const location = useLocation();
  const tab = new URLSearchParams(location.search).get("tab");
  const currentStep = FLOW_STEPS.find((s) => s.match(location.pathname, tab));

  return (
    <nav className="side-nav" aria-label="Main navigation">
      <div className="side-section">Demo path</div>
      <ol className="side-steps">
        {FLOW_STEPS.map((s) => {
          const active = currentStep?.id === s.id;
          const count = s.count ? counts[s.count] : 0;
          return (
            <li key={s.id}>
              <NavLink
                to={s.to}
                className={() => `side-step ${active ? "active" : ""}`}
                aria-current={active ? "page" : undefined}
                title={`${s.step}. ${s.label} — ${s.hint}`}
              >
                <span className="side-num" aria-hidden="true">{s.step}</span>
                <span className="side-text">
                  <span className="side-label">{s.label}{count ? <span className="side-count" aria-label={`${count} open`}>{count}</span> : null}</span>
                  <span className="side-hint">{s.hint}</span>
                  <span className="side-code">{s.code}</span>
                </span>
              </NavLink>
            </li>
          );
        })}
      </ol>

      <div className="side-section">More</div>
      <ul className="side-more">
        {MORE_LINKS.map((m) => {
          const active = !currentStep && m.match?.(location.pathname, tab);
          return (
            <li key={m.id}>
              {m.action === "audit" ? (
                <button type="button" className="side-link" onClick={onAudit} title={m.label}>
                  <Icon name={m.icon} size={16} /><span className="side-text">{m.label}</span>
                </button>
              ) : (
                <NavLink to={m.to} className={() => `side-link ${active ? "active" : ""}`} aria-current={active ? "page" : undefined} title={m.label}>
                  <Icon name={m.icon} size={16} /><span className="side-text">{m.label}{m.code ? <span className="side-code-inline">{m.code}</span> : null}</span>
                </NavLink>
              )}
            </li>
          );
        })}
        <li>
          <button type="button" className="side-link" onClick={onLauncher} aria-haspopup="dialog" title="All modules">
            <Icon name="search" size={16} /><span className="side-text">All modules…</span>
          </button>
        </li>
      </ul>
    </nav>
  );
}

/** "Previous / Next" at the end of each flow screen, so the demo walks the eight screens in order. */
export function FlowFooter() {
  const location = useLocation();
  const tab = new URLSearchParams(location.search).get("tab");
  const index = FLOW_STEPS.findIndex((s) => s.match(location.pathname, tab));
  if (index < 0) return null;
  const prev = FLOW_STEPS[index - 1];
  const next = FLOW_STEPS[index + 1];
  return (
    <nav className="flow-footer" aria-label="Demo path">
      {prev ? (
        <NavLink to={prev.to} className="flow-link">
          <span className="flow-dir">← Previous</span><span>{prev.step}. {prev.label}</span>
        </NavLink>
      ) : <span />}
      <span className="flow-pos">Step {index + 1} of {FLOW_STEPS.length} · {FLOW_STEPS[index].label}</span>
      {next ? (
        <NavLink to={next.to} className="flow-link flow-next">
          <span className="flow-dir">Next →</span><span>{next.step}. {next.label}</span>
        </NavLink>
      ) : <span className="flow-pos">End of the demo path — say what was real and what was seeded.</span>}
    </nav>
  );
}
