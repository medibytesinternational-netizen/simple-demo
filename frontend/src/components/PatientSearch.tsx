import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { usePatientDirectory } from "./patientDirectory";
import { useOpenChart } from "./openChart";
import { Icon } from "./icons";

/**
 * Header patient search over the real patient directory (hospital overview rows
 * plus any preview-registered patients). Opens the full chart when one exists,
 * otherwise the patient's details on the Patient list.
 */
export function PatientSearch() {
  const navigate = useNavigate();
  const directory = usePatientDirectory();
  const openChart = useOpenChart();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement | null>(null);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return directory.rows.filter((r) => r.name.toLowerCase().includes(q) || r.mrn.toLowerCase().includes(q)).slice(0, 6);
  }, [query, directory.rows]);

  const go = (id: string, chart: boolean) => {
    setOpen(false);
    setQuery("");
    if (chart) openChart(id);
    else navigate(`/patients?patient=${encodeURIComponent(id)}`);
  };

  return (
    <div className="patient-search" role="search">
      <Icon name="search" size={16} className="patient-search-icon" />
      <input
        ref={input}
        className="patient-search-input"
        placeholder="Search patients by name or MRN"
        aria-label="Search patients by name or MRN"
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls="patient-search-results"
        value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); setIndex(0); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setIndex((i) => Math.min(i + 1, results.length - 1)); }
          if (e.key === "ArrowUp") { e.preventDefault(); setIndex((i) => Math.max(i - 1, 0)); }
          if (e.key === "Enter" && results[index]) go(results[index].id, results[index].chartAvailable);
          if (e.key === "Escape") { setOpen(false); input.current?.blur(); }
        }}
      />
      {open && query.trim() ? (
        <ul className="patient-search-results" id="patient-search-results" role="listbox">
          {results.map((r, i) => (
            <li key={r.id} role="option" aria-selected={i === index}>
              <button type="button" className={`ps-result ${i === index ? "active" : ""}`} onMouseDown={(e) => e.preventDefault()} onClick={() => go(r.id, r.chartAvailable)}>
                <span className="ps-name">{r.name}</span>
                <span className="ps-meta">{r.mrn}{r.ward ? ` · ${r.ward} · ${r.bed}` : ""}</span>
                <span className="ps-tag">{r.chartAvailable ? "Open chart" : "Summary"}</span>
              </button>
            </li>
          ))}
          {!results.length ? <li className="ps-empty">No patient matches “{query}”.</li> : null}
        </ul>
      ) : null}
    </div>
  );
}
