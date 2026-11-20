import { Link, Navigate, useLocation } from "react-router-dom";
import { COUNT_TONE, NAV_GROUPS, type CountKey } from "./modules";
import { ROLES, STAFF, canSee, currentRole, type AppRole } from "./roles";
import { Icon } from "./icons";

// ASCII-only file (see Shell.tsx).
const SEP = String.fromCharCode(183);

/* ---------------------------------------------------------------- top bar */

export function TopBar({ role, userId, counts, preview, onMenu, onSearch, onControls, onSwitchUser }: {
  role: AppRole;
  userId: string;
  counts: Record<CountKey, number>;
  preview?: string;
  onMenu: () => void;
  onSearch: () => void;
  onControls: () => void;
  onSwitchUser: (id: string) => void;
}) {
  const showAlerts = canSee(role, "alerts");
  return (
    <header className="hx-top">
      <button type="button" className="hx-icon-btn hx-menu-btn" onClick={onMenu} aria-label="Show or hide navigation">
        <Icon name="menu" size={18} />
      </button>
      <Link to={ROLES[role].home} className="hx-brand">MediBytes <span>HMS</span></Link>
      {preview ? <span className="hx-preview">{preview}</span> : null}

      <button type="button" className="hx-search" onClick={onSearch} aria-label="Search pages or patients (Ctrl+K)">
        <Icon name="search" size={15} />
        <span className="hx-search-text">Search pages or patients</span>
        <kbd>Ctrl K</kbd>
      </button>

      <div className="hx-top-right">
        {showAlerts ? (
          <Link to="/safety?tab=alerts" className="hx-alerts" aria-label={`${counts.alerts} open alerts`} title="Open alerts">
            <Icon name="alert" size={16} />
            <span className="hx-hide-sm">Alerts</span>
            {counts.alerts ? <b>{counts.alerts}</b> : null}
          </Link>
        ) : null}
        <label className="hx-role">
          <span className="hx-hide-sm">Role</span>
          <select value={userId} onChange={(e) => onSwitchUser(e.target.value)} aria-label="Sign in as">
            {STAFF.map((s) => <option key={s.id} value={s.id}>{s.label} {SEP} {s.name}</option>)}
          </select>
        </label>
        <button type="button" className="hx-icon-btn" onClick={onControls} aria-label="Workspace settings" title="Workspace settings">
          <Icon name="more" size={18} />
        </button>
      </div>
    </header>
  );
}

/* ---------------------------------------------------------- patient banner */

export type PatientInfo = { name: string; mrn: string; age?: number; sex?: string; place: string; allergies: string[] };

/** Fixed identity strip on every patient page: who this is, where they are, what they react to. */
export function PatientBar({ patient }: { patient: PatientInfo }) {
  return (
    <div className="hx-patient" aria-label="Open patient">
      <Icon name="user" size={16} />
      <strong className="hx-pt-name">{patient.name}</strong>
      <span><b>MRN</b> {patient.mrn}</span>
      {patient.age != null ? <span><b>Age/Sex</b> {patient.age} / {(patient.sex || "")[0]?.toUpperCase()}</span> : null}
      {patient.place ? <span><b>Ward/Bed</b> {patient.place}</span> : null}
      {patient.allergies.length
        ? <span className="hx-pt-allergy"><b>Allergy</b> {patient.allergies.join(", ")}</span>
        : <span className="hx-pt-nka"><b>Allergy</b> None recorded</span>}
    </div>
  );
}

/* ---------------------------------------------------------------- sidebar */

export function Sidebar({ role, counts, patientName, inPatient, open, collapsed, onClose, onToggleCollapsed }: {
  role: AppRole;
  counts: Record<CountKey, number>;
  patientName?: string;
  inPatient: boolean;
  open: boolean;
  collapsed: boolean;
  onClose: () => void;
  onToggleCollapsed: () => void;
}) {
  const location = useLocation();
  const tab = new URLSearchParams(location.search).get("tab");

  const groups = NAV_GROUPS
    .map((g) => ({ ...g, items: g.items.filter((i) => canSee(role, i.id)) }))
    .filter((g) => g.items.length);
  const hospital = groups.filter((g) => g.scope === "hospital");
  const patient = groups.filter((g) => g.scope === "patient");
  const patientHome = patient[0]?.items[0];

  const renderGroup = (g: (typeof groups)[number], showTitle: boolean) => (
    <div key={g.id} className="hx-nav-group">
      {showTitle ? <div className="hx-nav-title">{g.title}</div> : null}
      <ul>
        {g.items.map((item) => {
          const active = item.match(location.pathname, tab);
          const count = item.count ? counts[item.count] : 0;
          return (
            <li key={item.id}>
              <Link
                to={item.to}
                className={`hx-nav-item${active ? " active" : ""}`}
                aria-current={active ? "page" : undefined}
                title={collapsed ? item.label : item.hint}
                onClick={onClose}
              >
                <Icon name={item.icon} size={17} />
                <span className="hx-nav-label">{item.label}</span>
                {count ? <span className={`hx-count ${COUNT_TONE[item.count!]}`}>{count}</span> : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );

  return (
    <>
      {open ? <div className="hx-scrim" onClick={onClose} aria-hidden="true" /> : null}
      <nav className={`hx-side${open ? " open" : ""}${collapsed ? " collapsed" : ""}`} aria-label="Main navigation">
        <div className="hx-side-scroll">
          {hospital.map((g) => renderGroup(g, true))}

          {patient.length ? (
            inPatient ? (
              <div className="hx-side-patient">
                <div className="hx-side-patient-head">
                  <span className="hx-nav-title">Patient</span>
                  <span className="hx-side-patient-name" title={patientName}>{patientName || ""}</span>
                </div>
                {patient.map((g, i) => renderGroup(g, i > 0))}
              </div>
            ) : patientHome ? (
              <div className="hx-nav-group">
                <div className="hx-nav-title">Patient</div>
                <Link to={patientHome.to} className="hx-nav-item hx-open-patient" onClick={onClose} title="Open patient record">
                  <Icon name="user" size={17} />
                  <span className="hx-nav-label">{patientName ? `Open ${patientName}` : "Open patient"}</span>
                  <Icon name="chevron" size={14} />
                </Link>
              </div>
            ) : null
          ) : null}
        </div>
        <button type="button" className="hx-collapse" onClick={onToggleCollapsed} aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}>
          <Icon name={collapsed ? "chevron" : "back"} size={15} />
          <span className="hx-nav-label">Collapse</span>
        </button>
      </nav>
    </>
  );
}

/* ------------------------------------------------------------- page guard */

/** "/" and unknown paths: send each role to its own start page. */
export function RoleHome() {
  return <Navigate to={ROLES[currentRole()].home} replace />;
}

export function NotForRole({ role, page }: { role: AppRole; page: string }) {
  return (
    <div className="page">
      <section className="his-box">
        <h2 className="his-box-title">Not available</h2>
        <p className="his-box-empty">
          {page} is not part of the {ROLES[role].label} view. <Link to={ROLES[role].home}>Go to your start page</Link>.
        </p>
      </section>
    </div>
  );
}
