import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DEMO_MODE } from "../demo/config";
import { previewStore } from "../demo/previewStore";
import { PatientDrawer } from "../components/PatientDrawer";
import { PatientForm } from "../components/PatientForm";
import { usePatientDirectory } from "../components/patientDirectory";
import type { DirectoryRow } from "../components/patientDirectory";
import { useOpenChart } from "../components/openChart";
import { Icon } from "../components/icons";
import { Banner, DataTable, EmptyState, Menu, MenuItem, Pill, SearchInput, Skeleton, Toolbar } from "../components/ui";
import type { Column, SortState } from "../components/ui";

type SortKey = "urgency" | "name" | "age" | "ward";

function urgency(row: DirectoryRow) {
  return row.criticalAlerts * 100 + row.openAlerts * 10 + row.overdueTasks + (row.status === "active" ? 1 : 0);
}

export function PatientsPage() {
  const directory = usePatientDirectory();
  const openChart = useOpenChart();
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

  // ---------- Render-only state and values ----------
  // Gallery is the default on phones, where the wide table would scroll sideways.
  const [view, setView] = useState<"list" | "gallery">(() => {
    try { return window.matchMedia("(max-width: 600px)").matches ? "gallery" : "list"; } catch { return "list"; }
  });
  const SORT_LABEL: Record<SortKey, string> = { urgency: "Most urgent", name: "Name", age: "Age (oldest first)", ward: "Ward and bed" };
  const STATUS_LABEL: Record<string, string> = { active: "Active encounter", discharged: "Discharged", "not admitted": "Not admitted" };
  // The table header shows the page's own sort; clicking the active column again returns to "most urgent".
  const tableSort: SortState = { key: sort, dir: sort === "name" || sort === "ward" ? "asc" : "desc" };
  const onTableSort = (next: SortState) => setSort(next && next.key !== sort && next.key in SORT_LABEL ? (next.key as SortKey) : "urgency");
  const activeFilters = (ward !== "all" ? 1 : 0) + (status !== "all" ? 1 : 0) + (criticalOnly ? 1 : 0);
  const clearFilters = () => { setQuery(""); setWard("all"); setStatus("all"); setCriticalOnly(false); };
  const total = directory.rows.length;
  const activeCount = directory.rows.filter((r) => r.status === "active").length;
  const criticalCount = directory.rows.filter((r) => r.criticalAlerts > 0).length;
  const overdueCount = directory.rows.filter((r) => r.overdueTasks > 0).length;
  const initials = (name: string) => name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();

  const allergyPill = (r: DirectoryRow, unknown = "Not available") => r.allergies.length
    ? <Pill tone="critical" icon="alert" title="Recorded allergies">{r.allergies.join(", ")}</Pill>
    : r.allergiesKnown
      ? <Pill tone="neutral" title="No known drug allergies">NKDA</Pill>
      : <Pill tone="warning" title="The allergy record is not open in this view">{unknown}</Pill>;
  const alertPills = (r: DirectoryRow) => (
    <>
      {r.criticalAlerts ? <Pill tone="critical" dot>{r.openAlerts} open · {r.criticalAlerts} critical</Pill>
        : r.openAlerts ? <Pill tone="warning" dot>{r.openAlerts} open</Pill> : null}
      {r.overdueTasks ? <Pill tone="warning" icon="clock">{r.overdueTasks} overdue</Pill> : null}
    </>
  );
  const statusPill = (r: DirectoryRow) => <Pill tone={r.status === "active" ? "success" : "neutral"}>{STATUS_LABEL[r.status] || r.status}</Pill>;
  const recordActions = (r: DirectoryRow) => (
    <>
      <button type="button" className="dk-btn dk-btn-outline dk-btn-sm" onClick={(e) => { e.stopPropagation(); setSelectedId(r.id); }} aria-label={`View details for ${r.name}`}>Details</button>
      {r.chartAvailable ? (
        <button type="button" className="dk-btn dk-btn-primary dk-btn-sm" onClick={(e) => { e.stopPropagation(); openChart(r.id); }} aria-label={`Open patient dashboard for ${r.name}`}>Open patient</button>
      ) : null}
    </>
  );
  const none = <span className="muted">n/a</span>;

  const columns: Column<DirectoryRow>[] = [
    {
      key: "name", header: "Patient", sort: (r) => r.name,
      cell: (r) => (
        <>
          <div className="pt-who">
            <span className={`dk-item-icon ${r.criticalAlerts ? "tone-critical" : r.status !== "active" ? "tone-muted" : ""}`} aria-hidden="true">{initials(r.name)}</span>
            <span>
              <div className="cell-strong nowrap">{r.name} {r.source === "preview" ? <Pill tone="warning">preview</Pill> : null}</div>
              <div className="cell-sub">{r.mrn}</div>
            </span>
          </div>
        </>
      ),
    },
    { key: "age", header: "Age / Sex", sort: (r) => r.age, className: "nowrap", cell: (r) => <>{r.age ?? "n/a"} {r.sex.slice(0, 1)}</> },
    {
      key: "allergies", header: "Allergies",
      cell: (r) => allergyPill(r),
    },
    { key: "kind", header: "Type", className: "nowrap", cell: (r) => r.kind || none },
    {
      key: "ward", header: "Ward / Bed", sort: (r) => r.ward, className: "nowrap",
      cell: (r) => (
        <>
          {r.ward ? `${r.ward} · ${r.bed}` : none}
          {r.previewEncounter ? <div className="cell-sub">preview admission</div> : null}
        </>
      ),
    },
    {
      key: "urgency", header: "Alerts", sort: (r) => r.criticalAlerts * 100 + r.openAlerts * 10 + r.overdueTasks,
      cell: (r) => (r.openAlerts || r.overdueTasks ? <span className="pill-row">{alertPills(r)}</span> : <span className="muted">None</span>),
    },
    { key: "status", header: "Status", cell: (r) => statusPill(r) },
    { key: "record", header: "Record", align: "right", className: "nowrap", cell: (r) => recordActions(r) },
  ];

  const emptyState = (
    <EmptyState icon="search" title="No patients match"
      action={filtersActive ? <button type="button" className="btn btn-sm" onClick={clearFilters}>Clear filters</button> : undefined}>
      {filtersActive ? "Try a different search or clear the filters." : "Registered patients appear here. Use Register patient to add one."}
    </EmptyState>
  );

  return (
    <div className="hms-page dk-page pg-patients">
      <header className="dk-head">
        <div>
          <h1 className="dk-title">Patient list</h1>
          <p className="dk-sub">Find a patient, see their summary, or open their dashboard.</p>
          {!DEMO_MODE ? <p className="dk-card-foot" id="registration-note">Registration needs the patient API, which is not enabled in this workspace.</p> : null}
        </div>
        <div className="dk-actions">
          <button type="button" className="dk-btn dk-btn-primary"
            onClick={() => setForm({ mode: "add" })}
            disabled={!DEMO_MODE}
            aria-describedby={!DEMO_MODE ? "registration-note" : undefined}
            title={DEMO_MODE ? "Register a patient in this preview tab" : "Registration needs the patient API, which is not enabled in this workspace"}>
            <Icon name="plus" size={16} /> Register patient
          </button>
        </div>
      </header>

      {notice ? (
        <Banner tone="success" role="status" actions={<button type="button" className="btn btn-ghost btn-sm" onClick={() => setNotice(null)}>Dismiss</button>}>{notice}</Banner>
      ) : null}
      {directory.error ? <Banner tone="danger" role="alert">Could not load patients: {directory.error.message}</Banner> : null}

      <section className="dk-kpis" aria-label="Patients at a glance">
        {directory.isLoading && !total ? Array.from({ length: 4 }, (_, i) => <div className="dk-kpi" key={i} aria-busy="true"><Skeleton count={3} /></div>) : (
          <>
            <button type="button" className={`dk-kpi is-feature ${!filtersActive ? "is-on" : ""}`} onClick={clearFilters} aria-pressed={!filtersActive}>
              <span className="dk-kpi-label">Total patients</span>
              <span className="dk-kpi-value">{total}</span>
              <span className="dk-kpi-note">on record · show all</span>
            </button>
            <button type="button" className={`dk-kpi ${status === "active" ? "is-on" : ""}`} onClick={() => setStatus(status === "active" ? "all" : "active")} aria-pressed={status === "active"}>
              <span className="dk-kpi-label">Active encounters</span>
              <span className="dk-kpi-value">{activeCount}</span>
              <span className="dk-kpi-note">{total - activeCount} not in care · filter</span>
            </button>
            <button type="button" className={`dk-kpi tone-critical ${criticalOnly ? "is-on" : ""}`} onClick={() => setCriticalOnly(!criticalOnly)} aria-pressed={criticalOnly}>
              <span className="dk-kpi-label">Critical alerts</span>
              <span className="dk-kpi-value">{criticalCount}</span>
              <span className="dk-kpi-note">{criticalCount === 1 ? "patient affected" : "patients affected"} · filter</span>
            </button>
            <div className="dk-kpi tone-warning">
              <span className="dk-kpi-label">Overdue tasks</span>
              <span className="dk-kpi-value">{overdueCount}</span>
              <span className="dk-kpi-note">{overdueCount === 1 ? "patient with a task overdue" : "patients with a task overdue"}</span>
            </div>
          </>
        )}
      </section>

      <section className="dk-card pt-panel" aria-label="Patients">
        <Toolbar label="Patient list tools">
          <SearchInput value={query} onChange={setQuery} placeholder="Search by name, MRN or patient ID" label="Search patients" />
          <Menu label="Filter" icon="filter" badge={activeFilters}>
            <div className="menu-label">Ward</div>
            <MenuItem checked={ward === "all"} onSelect={() => setWard("all")}>All wards</MenuItem>
            {wards.map((w) => <MenuItem key={w} checked={ward === w} onSelect={() => setWard(w)}>{w}</MenuItem>)}
            <div className="menu-sep" />
            <div className="menu-label">Encounter status</div>
            <MenuItem checked={status === "all"} onSelect={() => setStatus("all")}>All statuses</MenuItem>
            {(["active", "discharged", "not admitted"] as const).map((s) => (
              <MenuItem key={s} checked={status === s} onSelect={() => setStatus(s)}>{STATUS_LABEL[s]}</MenuItem>
            ))}
            <div className="menu-sep" />
            <MenuItem checkbox checked={criticalOnly} onSelect={() => setCriticalOnly(!criticalOnly)}>Critical alerts only</MenuItem>
          </Menu>
          <Menu label={`Sort: ${SORT_LABEL[sort].toLowerCase()}`} icon="sort">
            {(close) => (Object.keys(SORT_LABEL) as SortKey[]).map((key) => (
              <MenuItem key={key} checked={sort === key} onSelect={() => { setSort(key); close(); }}>{SORT_LABEL[key]}</MenuItem>
            ))}
          </Menu>
          <div className="segmented" role="group" aria-label="View">
            <button type="button" className={view === "list" ? "active" : ""} aria-pressed={view === "list"} onClick={() => setView("list")}>
              <Icon name="list" size={15} /> List
            </button>
            <button type="button" className={view === "gallery" ? "active" : ""} aria-pressed={view === "gallery"} onClick={() => setView("gallery")}>
              <Icon name="gallery" size={15} /> Gallery
            </button>
          </div>
          <span className="toolbar-count">{rows.length} shown</span>
        </Toolbar>

        {filtersActive ? (
          <div className="pt-chips" aria-label="Active filters">
            {query ? (
              <button type="button" className="chip active" onClick={() => setQuery("")} aria-label={`Remove search ${query}`}>
                Search: {query}<span className="chip-x" aria-hidden="true"><Icon name="close" size={12} /></span>
              </button>
            ) : null}
            {ward !== "all" ? (
              <button type="button" className="chip active" onClick={() => setWard("all")} aria-label={`Remove ward filter ${ward}`}>
                Ward: {ward}<span className="chip-x" aria-hidden="true"><Icon name="close" size={12} /></span>
              </button>
            ) : null}
            {status !== "all" ? (
              <button type="button" className="chip active" onClick={() => setStatus("all")} aria-label={`Remove status filter ${STATUS_LABEL[status] || status}`}>
                {STATUS_LABEL[status] || status}<span className="chip-x" aria-hidden="true"><Icon name="close" size={12} /></span>
              </button>
            ) : null}
            {criticalOnly ? (
              <button type="button" className="chip active" onClick={() => setCriticalOnly(false)} aria-label="Remove critical alerts only filter">
                Critical alerts only<span className="chip-x" aria-hidden="true"><Icon name="close" size={12} /></span>
              </button>
            ) : null}
            <button type="button" className="btn btn-ghost btn-sm" onClick={clearFilters}>Clear filters</button>
          </div>
        ) : null}

        {view === "list" ? (
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(r) => r.id}
            loading={directory.isLoading}
            onRowClick={(r) => setSelectedId(r.id)}
            sort={tableSort}
            onSort={onTableSort}
            pageSize={20}
            caption="Patients"
            empty={emptyState}
          />
        ) : directory.isLoading ? (
          <div className="pt-gallery"><Skeleton count={4} /></div>
        ) : !rows.length ? emptyState : (
          <ul className="pt-gallery">
            {rows.map((r) => (
              <li key={r.id} className="pt-card">
                <div className="pt-card-head">
                  <span className={`dk-item-icon ${r.criticalAlerts ? "tone-critical" : r.status !== "active" ? "tone-muted" : ""}`} aria-hidden="true">{initials(r.name)}</span>
                  <div className="pt-card-id">
                    <div className="cell-strong">{r.name} {r.source === "preview" ? <Pill tone="warning">preview</Pill> : null}</div>
                    <div className="cell-sub">{r.mrn} · {r.age ?? "n/a"} {r.sex.slice(0, 1)}</div>
                  </div>
                </div>
                <div className="cell-sub">
                  {r.ward ? `${r.ward} · ${r.bed}` : "No bed assigned"}{r.kind ? ` · ${r.kind}` : ""}{r.previewEncounter ? " · preview admission" : ""}
                </div>
                <div className="pill-row">
                  {statusPill(r)}
                  {allergyPill(r, "Allergies not available")}
                  {alertPills(r)}
                </div>
                <div className="pt-card-actions">{recordActions(r)}</div>
              </li>
            ))}
          </ul>
        )}
        <p className="dk-card-foot pt-foot">
          {DEMO_MODE
            ? "Preview environment: patients you add are kept in this browser tab only and are never saved. Only Ravi Menon has a full clinical chart in the available patient records."
            : "Only Ravi Menon has a full clinical chart. Other patients have summary records with alerts, tasks and medicine information."}
        </p>
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
