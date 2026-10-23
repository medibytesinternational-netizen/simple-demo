import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DEMO_MODE } from "../demo/config";
import { previewStore } from "../demo/previewStore";
import { PatientDrawer } from "../components/PatientDrawer";
import { PatientForm } from "../components/PatientForm";
import { usePatientDirectory } from "../components/patientDirectory";
import type { DirectoryRow } from "../components/patientDirectory";

type SortKey = "urgency" | "name" | "age" | "ward";

function urgency(row: DirectoryRow) {
  return row.criticalAlerts * 100 + row.openAlerts * 10 + row.overdueTasks + (row.status === "active" ? 1 : 0);
}

export function PatientsPage() {
  const directory = usePatientDirectory();
  const [query, setQuery] = useState("");
  const [ward, setWard] = useState("all");
  const [status, setStatus] = useState("all");
  const [criticalOnly, setCriticalOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("urgency");
  // ?patient=<id> (e.g. from the dashboard) opens that patient's details on arrival.
  const [params, setParams] = useSearchParams();
  const [selectedId, setSelectedIdState] = useState<string | null>(() => params.get("patient"));
  const setSelectedId = (id: string | null) => {
    setSelectedIdState(id);
    if (!id && params.has("patient")) setParams({}, { replace: true });
  };
  const [form, setForm] = useState<{ mode: "add" } | { mode: "edit"; id: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const wards = Array.from(new Set(directory.rows.map((r) => r.ward).filter(Boolean))) as string[];
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = directory.rows.filter((r) =>
      (!q || r.name.toLowerCase().includes(q) || r.mrn.toLowerCase().includes(q) || r.id.toLowerCase().includes(q)) &&
      (ward === "all" || r.ward === ward) &&
      (status === "all" || r.status === status) &&
      (!criticalOnly || r.criticalAlerts > 0),
    );
    const sorters: Record<SortKey, (a: DirectoryRow, b: DirectoryRow) => number> = {
      urgency: (a, b) => urgency(b) - urgency(a) || a.name.localeCompare(b.name),
      name: (a, b) => a.name.localeCompare(b.name),
      age: (a, b) => (b.age ?? 0) - (a.age ?? 0),
      ward: (a, b) => (a.ward || "~").localeCompare(b.ward || "~") || (a.bed || "").localeCompare(b.bed || ""),
    };
    return [...filtered].sort(sorters[sort]);
  }, [directory.rows, query, ward, status, criticalOnly, sort]);

  const selected = directory.rows.find((r) => r.id === selectedId) || null;
  const editing = form?.mode === "edit" ? directory.rows.find((r) => r.id === form.id)?.previewPatient : undefined;
  const existing = directory.rows.map((r) => ({ id: r.id, name: r.name, dob: r.dob }));
  const filtersActive = query || ward !== "all" || status !== "all" || criticalOnly;

  return (
    <div className="hms-page">
      <div className="crumbs"><Link to="/dashboard">Home</Link><span aria-hidden="true">›</span><span>Patients</span></div>
      <div className="hms-head">
        <div className="hms-title-row">
          <h1 className="hms-title">Patient List</h1>
          <span className="hms-sub">{directory.rows.length} patients · {directory.rows.filter((r) => r.status === "active").length} with an active encounter</span>
        </div>
        <div className="page-actions">
          {DEMO_MODE ? (
            <button className="btn btn-primary" onClick={() => setForm({ mode: "add" })}>+ Add new patient</button>
          ) : (
            <button className="btn btn-primary" disabled title="Patient registration needs the patient API (planned)">+ Add new patient</button>
          )}
        </div>
      </div>

      {notice ? <div className="success-box mb-3" role="status">{notice} <button className="btn btn-ghost btn-sm" onClick={() => setNotice(null)}>Dismiss</button></div> : null}
      {directory.error ? <div className="error-box mb-3">Could not load patients: {directory.error.message}</div> : null}

      <section className="card hms-card">
        <div className="filter-bar">
          <input className="input filter-search" placeholder="Search by name, MRN or patient ID" aria-label="Search patients" value={query} onChange={(e) => setQuery(e.target.value)} />
          <select className="select select-compact" value={ward} onChange={(e) => setWard(e.target.value)} aria-label="Ward">
            <option value="all">All wards</option>{wards.map((w) => <option key={w}>{w}</option>)}
          </select>
          <select className="select select-compact" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Encounter status">
            <option value="all">All statuses</option><option value="active">Active encounter</option><option value="discharged">Discharged</option><option value="not admitted">Not admitted</option>
          </select>
          <label className="check-inline"><input type="checkbox" className="checkbox" checked={criticalOnly} onChange={(e) => setCriticalOnly(e.target.checked)} /> Critical alerts only</label>
          <select className="select select-compact" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort by">
            <option value="urgency">Sort: most urgent</option><option value="name">Sort: name</option><option value="age">Sort: age</option><option value="ward">Sort: ward / bed</option>
          </select>
          {filtersActive ? <button className="btn btn-ghost btn-sm" onClick={() => { setQuery(""); setWard("all"); setStatus("all"); setCriticalOnly(false); }}>Clear filters</button> : null}
        </div>

        {directory.isLoading ? <div className="loading">Loading patients…</div> : null}
        {!directory.isLoading && !rows.length ? (
          <div className="empty"><div className="empty-title">No patients match</div>Try a different search or clear the filters.</div>
        ) : null}
        {rows.length ? (
          <div className="table-wrap">
            <table className="table hms-table">
              <thead><tr><th>Patient</th><th>Age / Sex</th><th>Allergies</th><th>Type</th><th>Ward / Bed</th><th>Alerts</th><th>Status</th><th className="right">Record</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={`clickable ${r.criticalAlerts ? "row-critical" : r.openAlerts || r.overdueTasks ? "row-warning" : ""}`} onClick={() => setSelectedId(r.id)}>
                    <td>
                      <div className="cell-strong nowrap">{r.name} {r.source === "preview" ? <span className="badge badge-warning">preview</span> : null}</div>
                      <div className="cell-sub">{r.mrn}</div>
                    </td>
                    <td className="nowrap">{r.age ?? "—"} {r.sex.slice(0, 1)}</td>
                    <td>{r.allergies.length ? <span className="badge badge-critical">{r.allergies.join(", ")}</span> : r.allergiesKnown ? <span className="muted small">NKDA</span> : <span className="badge badge-warning" title="The allergy record is not open in this view">Not available</span>}</td>
                    <td className="nowrap">{r.kind || "—"}</td>
                    <td className="nowrap">{r.ward ? `${r.ward} · ${r.bed}` : "—"}{r.previewEncounter ? <div className="cell-sub">preview admission</div> : null}</td>
                    <td>{r.openAlerts ? <span className={`count-pill ${r.criticalAlerts ? "critical" : "warning"}`}>{r.openAlerts}{r.criticalAlerts ? ` · ${r.criticalAlerts} crit` : ""}</span> : <span className="muted">—</span>}</td>
                    <td><span className={`badge ${r.status === "active" ? "badge-success" : "badge-neutral"}`}>{r.status}</span></td>
                    <td className="right nowrap">
                      <button className="btn btn-sm" onClick={(e) => { e.stopPropagation(); setSelectedId(r.id); }} aria-label={`View details for ${r.name}`}>Details</button>
                      {r.chartAvailable ? <Link className="btn btn-primary btn-sm" to="/timeline" onClick={(e) => e.stopPropagation()}>Chart</Link> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <div className="card-foot-note">
          {DEMO_MODE
            ? "UI preview: patients you add are kept in this browser tab only and are never saved. Only Ravi Menon has a full clinical chart in the synthetic data."
            : "Only Ravi Menon has a full clinical chart; other patients are summary-only until patient-scoped APIs exist. Registration is not available yet."}
        </div>
      </section>

      {selected ? (
        <PatientDrawer
          row={selected}
          onClose={() => setSelectedId(null)}
          onEdit={DEMO_MODE && selected.previewPatient ? () => setForm({ mode: "edit", id: selected.id }) : undefined}
        />
      ) : null}

      {form ? (
        <PatientForm
          title={form.mode === "add" ? "Register new patient (preview)" : "Edit patient (preview)"}
          submitLabel={form.mode === "add" ? "Add to preview list" : "Update preview record"}
          initial={editing}
          existing={existing}
          onCancel={() => setForm(null)}
          onSubmit={(input) => {
            if (form.mode === "add") {
              const patient = previewStore.addPatient(input);
              setNotice(`${patient.name} (${patient.mrn}) added to this preview tab. Not saved to any database.`);
            } else {
              previewStore.updatePatient(form.id, input);
              setNotice("Preview record updated in this tab. Not saved to any database.");
            }
            setForm(null);
          }}
        />
      ) : null}
    </div>
  );
}
