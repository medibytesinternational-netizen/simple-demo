import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DEMO_MODE, PREVIEW_SESSION_NOTE } from "../demo/config";
import { previewStore } from "../demo/previewStore";
import { usePatientDirectory } from "../components/patientDirectory";
import { ATTENDING, WARDS, bedKey } from "../components/wards";

const TYPES = ["IPD", "ICU", "Day care"];
const CHECKER = "Dr. Meera Shah";

function nowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

export function AdmissionPage() {
  const [params, setParams] = useSearchParams();
  const directory = usePatientDirectory();
  const [form, setForm] = useState({ kind: "IPD", ward: "", bed: "", attending: "", admittedAt: nowLocal(), reason: "", notes: "", allergyChecked: false });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const patientId = params.get("patient") || "";
  const patient = directory.rows.find((r) => r.id === patientId) || null;
  const wards = WARDS.filter((w) => w.kind === form.kind);
  const beds = useMemo(() => WARDS.find((w) => w.name === form.ward)?.beds || [], [form.ward]);

  const set = (key: string, value: any) => setForm((f) => ({ ...f, [key]: value, ...(key === "kind" ? { ward: "", bed: "" } : {}), ...(key === "ward" ? { bed: "" } : {}) }));

  function validate() {
    const e: Record<string, string> = {};
    if (!patient) e.patient = "Select a patient.";
    else if (patient.status === "active") e.patient = `${patient.name} already has an active encounter (${patient.ward} · ${patient.bed}). Discharge it before admitting again.`;
    if (!form.ward) e.ward = "Select a ward.";
    if (!form.bed) e.bed = "Select a bed.";
    else if (directory.occupied.has(bedKey(form.ward, form.bed))) e.bed = `This bed is occupied by ${directory.occupied.get(bedKey(form.ward, form.bed))}.`;
    if (!form.attending) e.attending = "Select the attending clinician.";
    if (!form.admittedAt) e.admittedAt = "Enter the admission date and time.";
    else if (new Date(form.admittedAt) > new Date()) e.admittedAt = "Admission time cannot be in the future.";
    if (form.reason.trim().length < 5) e.reason = "Describe the reason for admission (at least 5 characters).";
    if (!form.allergyChecked) e.allergyChecked = "A clinician must verify the allergy record before admission.";
    return e;
  }

  function submit() {
    const e = validate();
    setErrors(e);
    if (Object.keys(e).length || !DEMO_MODE || !patient) return;
    previewStore.addEncounter({
      patientId: patient.id, kind: form.kind, ward: form.ward, bed: form.bed, attending: form.attending,
      admittedAt: new Date(form.admittedAt).toISOString(), reason: form.reason.trim(), notes: form.notes.trim(), allergyCheckedBy: CHECKER,
    });
    setNotice(`${patient.name} shown as admitted to ${form.ward} · ${form.bed} in this preview tab only. No encounter was created in any hospital system.`);
    setForm({ kind: "IPD", ward: "", bed: "", attending: "", admittedAt: nowLocal(), reason: "", notes: "", allergyChecked: false });
  }

  const err = (key: string) => (errors[key] ? <div className="field-error" role="alert">{errors[key]}</div> : null);

  return (
    <div className="hms-page">
      <div className="crumbs"><Link to="/dashboard">Home</Link><span aria-hidden="true">›</span><span>Admission</span></div>
      <div className="hms-head">
        <div className="hms-title-row">
          <h1 className="hms-title">Admission</h1>
          <span className="hms-sub">Create an inpatient, ICU or day-care encounter for an existing patient</span>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/notes?tab=admission">AI-assisted admission assessment (F2)</Link>
        </div>
      </div>

      {DEMO_MODE ? <div className="banner warning mb-3">{PREVIEW_SESSION_NOTE}</div> : (
        <div className="banner mb-3">Creating admissions needs the encounter API, which is not available yet. The form shows the planned workflow; submission is disabled. The existing AI-assisted admission assessment (F2) remains available for the current patient.</div>
      )}
      {notice ? <div className="success-box mb-3" role="status">{notice}</div> : null}
      {directory.error ? <div className="error-box mb-3">Could not load patients: {directory.error.message}</div> : null}

      <div className="admission-grid">
        <section className="card hms-card">
          <div className="hms-card-head"><h2 className="hms-card-title">1 · Patient</h2></div>
          <div className="card-pad flex-col gap-3">
            <div className="form-field">
              <label className="field-label" htmlFor="adm-patient">Patient<span className="req"> *</span></label>
              <select id="adm-patient" className={`select ${errors.patient ? "invalid" : ""}`} value={patientId} onChange={(e) => { setParams(e.target.value ? { patient: e.target.value } : {}); setErrors({}); setNotice(null); }}>
                <option value="">Select a patient…</option>
                {directory.rows.map((r) => (
                  <option key={r.id} value={r.id}>{r.name} · {r.mrn}{r.status === "active" ? " — already admitted" : ""}</option>
                ))}
              </select>
              {err("patient")}
            </div>
            {patient ? (
              <dl className="kv">
                <dt>MRN</dt><dd className="mono">{patient.mrn}</dd>
                <dt>Age / sex</dt><dd>{patient.age ?? "—"} · {patient.sex}</dd>
                <dt>Current status</dt><dd>{patient.status === "active" ? `Active · ${patient.ward} · ${patient.bed}` : patient.status}</dd>
                <dt>Problems</dt><dd>{patient.problems.join(" · ") || "None recorded"}</dd>
              </dl>
            ) : <div className="small muted">Choose a registered patient. New patients are added from the Patient List.</div>}
            {patient ? (
              <div className={`allergy-panel ${patient.allergies.length ? "" : "none"}`}>
                <div className="section-label" style={{ margin: 0 }}>Recorded allergies</div>
                <div className="fs-13 mt-1">{patient.allergies.length ? patient.allergies.join(", ") : "No known drug allergies recorded"}</div>
                <label className="check-inline mt-2">
                  <input type="checkbox" className="checkbox" checked={form.allergyChecked} onChange={(e) => set("allergyChecked", e.target.checked)} />
                  I have verified this allergy record with the patient or carer ({CHECKER})
                </label>
                {err("allergyChecked")}
              </div>
            ) : null}
          </div>
        </section>

        <section className="card hms-card">
          <div className="hms-card-head"><h2 className="hms-card-title">2 · Admission details</h2></div>
          <div className="card-pad form-grid">
            <div className="form-field">
              <label className="field-label" htmlFor="adm-kind">Encounter type<span className="req"> *</span></label>
              <select id="adm-kind" className="select" value={form.kind} onChange={(e) => set("kind", e.target.value)}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select>
            </div>
            <div className="form-field">
              <label className="field-label" htmlFor="adm-at">Admission date and time<span className="req"> *</span></label>
              <input id="adm-at" type="datetime-local" className={`input ${errors.admittedAt ? "invalid" : ""}`} value={form.admittedAt} onChange={(e) => set("admittedAt", e.target.value)} />
              {err("admittedAt")}
            </div>
            <div className="form-field">
              <label className="field-label" htmlFor="adm-ward">Ward<span className="req"> *</span></label>
              <select id="adm-ward" className={`select ${errors.ward ? "invalid" : ""}`} value={form.ward} onChange={(e) => set("ward", e.target.value)}>
                <option value="">Select a ward…</option>{wards.map((w) => <option key={w.name}>{w.name}</option>)}
              </select>
              {err("ward")}
            </div>
            <div className="form-field">
              <label className="field-label" htmlFor="adm-bed">Bed<span className="req"> *</span></label>
              <select id="adm-bed" className={`select ${errors.bed ? "invalid" : ""}`} value={form.bed} onChange={(e) => set("bed", e.target.value)} disabled={!form.ward}>
                <option value="">{form.ward ? "Select a bed…" : "Select a ward first"}</option>
                {beds.map((b) => {
                  const holder = directory.occupied.get(bedKey(form.ward, b));
                  return <option key={b} value={b} disabled={!!holder}>{b}{holder ? ` — occupied (${holder})` : " — free"}</option>;
                })}
              </select>
              {err("bed")}
            </div>
            <div className="form-field">
              <label className="field-label" htmlFor="adm-att">Attending clinician<span className="req"> *</span></label>
              <select id="adm-att" className={`select ${errors.attending ? "invalid" : ""}`} value={form.attending} onChange={(e) => set("attending", e.target.value)}>
                <option value="">Select…</option>{ATTENDING.map((a) => <option key={a}>{a}</option>)}
              </select>
              {err("attending")}
            </div>
            <div className="form-span form-field">
              <label className="field-label" htmlFor="adm-reason">Reason for admission<span className="req"> *</span></label>
              <textarea id="adm-reason" className={`textarea small ${errors.reason ? "invalid" : ""}`} value={form.reason} onChange={(e) => set("reason", e.target.value)} placeholder="Presenting problem and why admission is needed" />
              {err("reason")}
            </div>
            <div className="form-span form-field">
              <label className="field-label" htmlFor="adm-notes">Relevant clinical information</label>
              <textarea id="adm-notes" className="textarea small" value={form.notes} onChange={(e) => set("notes", e.target.value)} placeholder="Optional. Entered by the clinician; nothing is generated." />
            </div>
          </div>
          <div className="card-foot-actions">
            {DEMO_MODE ? (
              <button className="btn btn-primary" onClick={submit}>Record admission (preview)</button>
            ) : (
              <button className="btn btn-primary" disabled title="Needs the encounter API (planned)">Admit patient</button>
            )}
            <span className="small muted">Required: patient, ward, free bed, attending, time, reason and allergy verification.</span>
          </div>
        </section>
      </div>
    </div>
  );
}
