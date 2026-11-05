import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { COUNT_TONE, NAV_GROUPS, isPatientRoute, type CountKey } from "../modules";

// ASCII-only file (see Shell.tsx).
const SEP = String.fromCharCode(183);
const ARROW = String.fromCharCode(8594);

/** Staff who can sign in. The chief assigns tasks; the others see and work their own. */
export const STAFF = [
  { id: "u_meera", name: "Dr. Meera Shah", role: "doctor", label: "Chief doctor" },
  { id: "u_arjun", name: "Dr. Arjun Rao", role: "senior_doctor", label: "Senior doctor" },
  { id: "u_anita", name: "Nurse Anita Rao", role: "nurse", label: "Nurse" },
];

export function StatusBar({ loginId, user, hospital, screen, onControls, userId, onSwitchUser }: {
  loginId: string; user: string; hospital: string; screen: string; onControls: () => void;
  userId: string; onSwitchUser: (id: string) => void;
}) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(t);
  }, []);
  const fullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen?.();
  };
  return (
    <header className="his-status">
      <span className="his-status-item"><b>LOGIN ID={loginId}</b></span>
      <span className="his-status-item"><b>LOGIN NAME={user.toUpperCase()}</b></span>
      <label className="his-role">
        <span>ROLE</span>
        <select value={userId} onChange={(e) => onSwitchUser(e.target.value)} aria-label="Sign in as">
          {STAFF.map((s) => <option key={s.id} value={s.id}>{s.label}: {s.name}</option>)}
        </select>
      </label>
      <span className="his-status-item his-hide-sm">{hospital.toUpperCase()} {SEP} WARD WORKSTATION</span>
      <button type="button" className="his-status-btn" onClick={fullscreen}>Fullscreen</button>
      <button type="button" className="his-status-btn" onClick={onControls}>Workspace</button>
      <span className="his-screen-tag">[{screen.toUpperCase()}]</span>
      <span className="his-clock" title="Application time">
        {now.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", second: "2-digit" })}
      </span>
      <span className="his-version his-hide-sm">[2.1.0.1279]</span>
    </header>
  );
}

type PatientInfo = { name: string; mrn: string; age?: number; sex?: string; place: string; allergies: string[] } | null;

export function MenuBar({ counts, patient }: { counts: Record<CountKey, number>; patient: PatientInfo }) {
  const location = useLocation();
  const tab = new URLSearchParams(location.search).get("tab");
  const onList = location.pathname === "/patients";
  // Patient workspace = the patient list plus every page about the opened patient.
  const inPatient = onList || isPatientRoute(location.pathname);
  const opened = inPatient && !onList;

  const groups = NAV_GROUPS
    .map((g) => ({
      ...g,
      items: g.items.filter((i) => {
        const path = i.to.split("?")[0];
        if (path === "/patients") return inPatient;          // patient list lives in the patient tab
        return isPatientRoute(path) ? opened : !inPatient;   // patient pages only once a patient is open
      }),
    }))
    .filter((g) => g.items.length);
  const current = groups.find((g) => g.items.some((i) => i.match(location.pathname, tab))) || groups[0];
  const [picked, setPicked] = useState<string | null>(null);
  useEffect(() => setPicked(null), [location.pathname, location.search]);
  const open = groups.find((g) => g.id === picked) || current;
  const groupCount = (items: typeof open.items) => items.reduce((n, i) => n + (i.count ? counts[i.count] : 0), 0);

  return (
    <nav className={`his-menu ${inPatient ? "is-patient" : "is-hospital"}`} aria-label="Main menu">
      <div className="his-workspace" role="tablist" aria-label="Workspace">
        <Link to="/dashboard" role="tab" aria-selected={!inPatient} className={`his-ws his-ws-hospital${!inPatient ? " on" : ""}`}>
          HOSPITAL
        </Link>
        <Link to="/patients" role="tab" aria-selected={inPatient} className={`his-ws his-ws-patient${inPatient ? " on" : ""}`}>
          PATIENT{opened && patient ? `: ${patient.name.toUpperCase()}` : ""}
        </Link>
        {opened && patient ? (
          <div className="his-pt-strip" aria-label="Open patient">
            <span><b>MRN</b> {patient.mrn}</span>
            {patient.age != null ? <span><b>AGE/SEX</b> {patient.age} / {(patient.sex || "")[0]?.toUpperCase()}</span> : null}
            {patient.place ? <span><b>WARD/BED</b> {patient.place}</span> : null}
            {patient.allergies.length ? <span className="his-pt-allergy"><b>ALLERGY</b> {patient.allergies.join(", ")}</span> : null}
          </div>
        ) : (
          <span className="his-ws-hint">{onList ? "Choose a patient and click Open patient to see their dashboard." : "Hospital-wide view and monitoring."}</span>
        )}
        <Link to="/discharge" className="his-menu-item primary his-quick">Discharge Summary</Link>
        <Link to="/safety?tab=alerts" className="his-menu-item primary his-quick">
          Emergency {SEP} Alerts {ARROW}{counts.alerts ? <span className="his-menu-count critical">{counts.alerts}</span> : null}
        </Link>
      </div>
      <div className="his-menu-groups" role="tablist" aria-label="Sections">
        {groups.map((g) => {
          const n = groupCount(g.items);
          return (
            <button
              key={g.id}
              type="button"
              role="tab"
              aria-selected={g.id === open.id}
              className={`his-group${g.id === open.id ? " open" : ""}${g.id === current.id ? " current" : ""}`}
              onClick={() => setPicked(g.id)}
            >
              {g.title}
              {n ? <span className="his-menu-count">{n}</span> : null}
            </button>
          );
        })}
      </div>
      <div className="his-menu-items">
        <span className="his-menu-crumb">{open.title}:</span>
        {open.items.map((item) => {
          const active = item.match(location.pathname, tab);
          const count = item.count ? counts[item.count] : 0;
          return (
            <Link
              key={item.id}
              to={item.to}
              className={`his-menu-item${active ? " active" : ""}`}
              aria-current={active ? "page" : undefined}
              title={item.hint}
            >
              {item.label}
              {count ? <span className={`his-menu-count ${COUNT_TONE[item.count!]}`}>{count}</span> : null}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

export function FooterBar({ hospital, status }: { hospital: string; status: string }) {
  return (
    <footer className="his-footer">
      <span>Ready {SEP} {hospital} (IP Ward Workstation)</span>
      <span>Packet Status: {status}</span>
    </footer>
  );
}
