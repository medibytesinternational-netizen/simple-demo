import { useMemo, useState, type KeyboardEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ALL_ITEMS, COUNT_TONE, NAV_GROUPS, type CountKey, type NavItem } from "./modules";
import { usePatientDirectory } from "./patientDirectory";
import { useOpenChart } from "./openChart";
import { Icon } from "./icons";
import { useDialog } from "./ui/useDialog";

function matches(item: NavItem & { group?: string }, q: string) {
  const hay = [item.label, item.hint, item.group || "", ...(item.keywords || [])].join(" ").toLowerCase();
  return q.split(/\s+/).every((word) => hay.includes(word));
}

/** Move focus between tiles like a grid: left/right by one, up/down to the nearest tile in the next row. */
function moveFocus(e: KeyboardEvent<HTMLElement>, root: HTMLElement | null) {
  if (!root || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
  const tiles = Array.from(root.querySelectorAll<HTMLElement>(".lp-tile"));
  const index = tiles.indexOf(document.activeElement as HTMLElement);
  if (index < 0) {
    if (e.key === "ArrowDown" && tiles[0]) { e.preventDefault(); tiles[0].focus(); }
    return;
  }
  e.preventDefault();
  if (e.key === "ArrowLeft") return tiles[Math.max(0, index - 1)]?.focus();
  if (e.key === "ArrowRight") return tiles[Math.min(tiles.length - 1, index + 1)]?.focus();
  const here = tiles[index].getBoundingClientRect();
  const down = e.key === "ArrowDown";
  let best: HTMLElement | null = null;
  let bestScore = Infinity;
  for (const tile of tiles) {
    const r = tile.getBoundingClientRect();
    const dy = down ? r.top - here.top : here.top - r.top;
    if (dy <= 4) continue;
    const score = dy * 1000 + Math.abs(r.left - here.left);
    if (score < bestScore) { bestScore = score; best = tile; }
  }
  if (best) best.focus();
  else if (!down) root.querySelector<HTMLInputElement>(".launchpad-search input")?.focus();
}

export function Launchpad({ counts, onClose }: { counts: Record<CountKey, number>; onClose: () => void }) {
  const ref = useDialog<HTMLDivElement>(onClose, { initialFocus: ".launchpad-search input", lockScroll: true });
  const location = useLocation();
  const navigate = useNavigate();
  const tab = new URLSearchParams(location.search).get("tab");
  const directory = usePatientDirectory();
  const openChart = useOpenChart();
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();

  const groups = useMemo(() => {
    if (!q) return NAV_GROUPS;
    return NAV_GROUPS.map((g) => ({ ...g, items: g.items.filter((item) => matches({ ...item, group: g.title }, q)) })).filter((g) => g.items.length);
  }, [q]);
  const patients = useMemo(
    () => (q ? directory.rows.filter((r) => r.name.toLowerCase().includes(q) || r.mrn.toLowerCase().includes(q)).slice(0, 6) : []),
    [q, directory.rows],
  );

  const openPatient = (id: string, chart: boolean) => {
    onClose();
    if (chart) openChart(id);
    else navigate(`/patients?patient=${encodeURIComponent(id)}`);
  };
  const openFirst = () => {
    const first = ALL_ITEMS.find((item) => matches(item, q));
    if (q && first) { onClose(); navigate(first.to); return; }
    if (patients[0]) openPatient(patients[0].id, patients[0].chartAvailable);
  };

  return (
    <div ref={ref} className="launchpad" role="dialog" aria-modal="true" aria-label="All modules" tabIndex={-1} onKeyDown={(e) => moveFocus(e, ref.current)}>
      <div className="launchpad-top">
        <div className="launchpad-search" role="search">
          <Icon name="search" size={18} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); openFirst(); } }}
            placeholder="Search modules or patients"
            aria-label="Search modules or patients"
          />
        </div>
        <button type="button" className="chrome-btn icon-only launchpad-close" onClick={onClose} aria-label="Close all modules">
          <Icon name="close" size={18} />
        </button>
      </div>

      <div className="launchpad-body" onClick={(e) => { if (e.target === e.currentTarget || (e.target as HTMLElement).classList.contains("launchpad-inner")) onClose(); }}>
        <div className="launchpad-inner">
          {patients.length ? (
            <section aria-labelledby="lp-patients">
              <h2 className="lp-group-title" id="lp-patients">Patients</h2>
              <div className="lp-grid">
                {patients.map((p) => (
                  <button type="button" key={p.id} className="lp-tile" onClick={() => openPatient(p.id, p.chartAvailable)}>
                    <span className="lp-icon" aria-hidden="true"><Icon name="user" size={22} /></span>
                    <span className="lp-label">{p.name}</span>
                    <span className="lp-hint">{p.mrn}{p.ward ? ` · ${p.ward} · ${p.bed}` : ""} · {p.chartAvailable ? "Open chart" : "Summary"}</span>
                  </button>
                ))}
              </div>
            </section>
          ) : null}

          {groups.map((group) => (
            <section key={group.id} aria-labelledby={`lp-${group.id}`}>
              <h2 className="lp-group-title" id={`lp-${group.id}`}>{group.title}</h2>
              <div className="lp-grid">
                {group.items.map((item) => {
                  const count = item.count ? counts[item.count] : 0;
                  const active = item.match(location.pathname, tab);
                  return (
                    <Link key={item.id} to={item.to} className={`lp-tile ${active ? "active" : ""}`} aria-current={active ? "page" : undefined}
                      aria-label={count ? `${item.label}, ${count}` : undefined} onClick={onClose}>
                      <span className="lp-icon" aria-hidden="true"><Icon name={item.icon} size={22} /></span>
                      {count ? <span className={`lp-count ${COUNT_TONE[item.count!]}`} aria-hidden="true">{count}</span> : null}
                      <span className="lp-label">{item.label}</span>
                      <span className="lp-hint">{item.hint}</span>
                    </Link>
                  );
                })}
              </div>
            </section>
          ))}

          {!groups.length && !patients.length ? (
            <div className="lp-empty" role="status">
              <strong>Nothing matches "{query}"</strong>
              Try alerts, discharge, labs or a patient name.
            </div>
          ) : null}
        </div>
      </div>

      <div className="launchpad-foot" aria-hidden="true">
        <span><kbd>Esc</kbd> close</span>
        <span><kbd>&larr;</kbd> <kbd>&rarr;</kbd> <kbd>&uarr;</kbd> <kbd>&darr;</kbd> move</span>
        <span><kbd>Enter</kbd> open</span>
        <span><kbd>Ctrl</kbd> <kbd>K</kbd> open from anywhere</span>
      </div>
    </div>
  );
}
