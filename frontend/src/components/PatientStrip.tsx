import { Link } from "react-router-dom";
import type { Lab, Meta } from "../types";
import { Icon } from "./icons";

export function initials(name: string) {
  const parts = name.replace(/^(dr|mr|mrs|ms|prof)\.?\s+/i, "").split(" ").filter(Boolean);
  return parts.map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

/**
 * Glass identity strip for the patient whose record the clinical screens act on.
 * The allergy stays visible at every width.
 */
export function PatientStrip({ meta, openAlerts, egfr, stayDay }: { meta?: Meta; openAlerts: number; egfr?: Lab; stayDay: number | null }) {
  if (!meta) {
    return (
      <section className="patient-banner glass pb-loading" aria-label="Current patient" aria-busy="true">
        <span className="sk" style={{ width: 42, height: 42, borderRadius: "50%" }} />
        <span className="sk" style={{ width: 180, height: 14 }} />
        <span className="sr-only">Loading patient</span>
      </section>
    );
  }
  const { patient, encounter } = meta;
  return (
    <section className="patient-banner glass" aria-label="Current patient">
      <span className="avatar avatar-lg pb-avatar" aria-hidden="true">{initials(patient.name)}</span>
      <div className="pb-identity">
        <div className="pb-name">
          {patient.name}
          <span className="pb-record-tag" title="This patient has a full clinical record">Full record</span>
        </div>
        <div className="pb-meta">{patient.age} y · {patient.sex} · MRN {patient.mrn}</div>
      </div>
      <dl className="pb-facts">
        <div><Icon name="bed" size={16} /><span><dt>Location</dt><dd>{encounter.ward} · {encounter.bed}</dd></span></div>
        <div><Icon name="calendar" size={16} /><span><dt>Stay</dt><dd>{encounter.kind}{stayDay && encounter.status === "active" ? ` · day ${stayDay}` : ` · ${encounter.status}`}</dd></span></div>
        <div><Icon name="user" size={16} /><span><dt>Attending</dt><dd>{encounter.attending}</dd></span></div>
        {egfr ? <div className={egfr.flag === "low" || egfr.flag === "high" ? "pb-fact-flag" : ""}><Icon name="lab" size={16} /><span><dt>Latest eGFR</dt><dd className={egfr.flag === "low" || egfr.flag === "high" ? "pb-flag" : ""}>{egfr.value}{egfr.flag ? ` · ${egfr.flag}` : ""}</dd></span></div> : null}
      </dl>
      <div className="pb-status">
        <span className="pb-allergy"><Icon name="alert" size={15} /> Allergy: {patient.allergies.join(", ") || "none recorded"}</span>
        {openAlerts ? <Link className="pb-alerts" to="/safety?tab=alerts"><Icon name="safety" size={15} /> {openAlerts} open alert{openAlerts === 1 ? "" : "s"}</Link> : null}
      </div>
    </section>
  );
}
