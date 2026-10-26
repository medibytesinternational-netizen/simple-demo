import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DEMO_MODE, PREVIEW_SESSION_NOTE } from "../demo/config";
import { previewStore } from "../demo/previewStore";
import { usePatientDirectory } from "../components/patientDirectory";
import { ATTENDING, WARDS, bedKey } from "../components/wards";
import { ALLERGY_UNAVAILABLE, allergyGateError } from "../components/admissionRules";
import { PageHeader } from "../components/PageHeader";
import type { KeyboardEvent } from "react";
import { Banner, Field, Panel } from "../components/ui";

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
  // The patient whose allergy record the clinician verified. A verification counts only for that patient.
  const [form, setForm] = useState({ kind: "IPD", ward: "", bed: "", attending: "", admittedAt: nowLocal(), reason: "", notes: "", allergyVerifiedFor: null as string | null });
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
    const allergyError = allergyGateError(patient ? patient.allergiesKnown : true, form.allergyVerifiedFor === patient?.id);
    if (allergyError) e.allergyVerified = allergyError;
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
    setForm({ kind: "IPD", ward: "", bed: "", attending: "", admittedAt: nowLocal(), reason: "", notes: "", allergyVerifiedFor: null });
  }

  const err = (key: string) => (errors[key] ? <div className="field-error" role="alert">{errors[key]}</div> : null);

  const errorCount = Object.keys(errors).length;
  // Bed picker: radio chips over the same form.bed value the validation reads. Occupied beds cannot be chosen.
  const freeBeds = beds.filter((b) => !directory.occupied.has(bedKey(form.ward, b)));
  const tabBed = form.bed && freeBeds.includes(form.bed) ? form.bed : freeBeds[0];
  const onBedKey = (e: KeyboardEvent<HTMLButtonElement>, bed: string) => {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step || !freeBeds.length) return;
    e.preventDefault();
    const at = freeBeds.indexOf(bed);
    const next = freeBeds[(at + step + freeBeds.length) % freeBeds.length];
    set("bed", next);
    e.currentTarget.parentElement?.querySelector<HTMLElement>(`[data-bed="${next}"]`)?.focus();
  };

  return (
    <div className="hms-page pg-admission">
      <PageHeader
        title="New admission"
        description="Admit an existing patient to a ward and bed. This creates the stay; the clinical admission note is written in Admission assessment."
        actions={<Link className="btn" to="/notes?tab=admission">Go to admission assessment</Link>}
      />

      {DEMO_MODE ? <Banner tone="warning">{PREVIEW_SESSION_NOTE}</Banner> : (
        <Banner>Creating admissions needs the encounter API, which is not available yet. The form shows the planned workflow; submission is disabled. The AI-assisted admission assessment remains available for the current patient.</Banner>
      )}
      {directory.error ? <div className="error-box">Could not load patients: {directory.error.message}</div> : null}

      <div className="admission-grid">
        <Panel title="Patient" sub="Who is being admitted, and their allergy record." className="adm-patient">
          <div className="panel-body flex-col gap-3">
            <div className="form-field">
              <label className="field-label" htmlFor="adm-patient">Patient<span className="req"> *</span></label>
              <select id="adm-patient" className={`select ${errors.patient ? "invalid" : ""}`} value={patientId} onChange={(e) => { setParams(e.target.value ? { patient: e.target.value } : {}); setErrors({}); setNotice(null); }}>
                <option value="">Select a patient…</option>
                {directory.rows.map((r) => (
                  <option key={r.id} value={r.id}>{r.name} · {r.mrn}{r.status === "active" ? " (already admitted)" : ""}</option>
                ))}
              </select>
              {err("patient")}
            </div>
            {patient ? (
              <dl className="kv">
                <dt>MRN</dt><dd className="mono">{patient.mrn}</dd>
                <dt>Age / sex</dt><dd>{patient.age ?? "Not recorded"} · {patient.sex}</dd>
                <dt>Current status</dt><dd>{patient.status === "active" ? `Active · ${patient.ward} · ${patient.bed}` : patient.status}</dd>
                <dt>Problems</dt><dd>{patient.problems.join(" · ") || "None recorded"}</dd>
              </dl>
            ) : <div className="small muted">Choose a registered patient. New patients are added from the Patient List.</div>}
            {patient ? (
              <div className={`allergy-panel ${patient.allergies.length || !patient.allergiesKnown ? "" : "none"}`}>
                <div className="section-label" style={{ margin: 0 }}>Recorded allergies</div>
                <div className="fs-13 mt-1">{patient.allergies.length ? patient.allergies.join(", ") : patient.allergiesKnown ? "No known drug allergies recorded" : "Allergy record not available in this view. Check the hospital record before prescribing."}</div>
                {patient.allergiesKnown ? (
                  <>
                    <label className="check-inline mt-2">
                      <input type="checkbox" className="checkbox" checked={form.allergyVerifiedFor === patient.id} onChange={(e) => set("allergyVerifiedFor", e.target.checked ? patient.id : null)} />
                      I have verified this allergy record with the patient or carer ({CHECKER})
                    </label>
                    {err("allergyVerified")}
                  </>
                ) : (
                  <div className="field-error mt-2" role="alert" data-testid="allergy-unavailable">{ALLERGY_UNAVAILABLE}</div>
                )}
              </div>
            ) : null}
          </div>
        </Panel>

        <Panel title="Stay details" sub="Where the patient stays, under whom, and why." className="adm-stay">
          <div className="panel-body form-grid">
            <Field label="Encounter type" htmlFor="adm-kind" required>
              <select id="adm-kind" className="select" value={form.kind} onChange={(e) => set("kind", e.target.value)}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select>
            </Field>
            <Field label="Admission date and time" htmlFor="adm-at" required error={errors.admittedAt}>
              <input id="adm-at" type="datetime-local" className={`input ${errors.admittedAt ? "invalid" : ""}`} value={form.admittedAt} onChange={(e) => set("admittedAt", e.target.value)} />
            </Field>
            <Field label="Ward" htmlFor="adm-ward" required error={errors.ward}>
              <select id="adm-ward" className={`select ${errors.ward ? "invalid" : ""}`} value={form.ward} onChange={(e) => set("ward", e.target.value)}>
                <option value="">Select a ward…</option>{wards.map((w) => <option key={w.name}>{w.name}</option>)}
              </select>
            </Field>
            <Field label="Attending clinician" htmlFor="adm-att" required error={errors.attending}>
              <select id="adm-att" className={`select ${errors.attending ? "invalid" : ""}`} value={form.attending} onChange={(e) => set("attending", e.target.value)}>
                <option value="">Select…</option>{ATTENDING.map((a) => <option key={a}>{a}</option>)}
              </select>
            </Field>
            <div className="form-span form-field">
              <span className="field-label" id="adm-bed-label">Bed<span className="req"> *</span></span>
              {form.ward ? (
                <div className={`bed-grid ${errors.bed ? "invalid" : ""}`} role="radiogroup" aria-labelledby="adm-bed-label" aria-required="true">
                  {beds.map((b) => {
                    const holder = directory.occupied.get(bedKey(form.ward, b));
                    return (
                      <button
                        key={b}
                        type="button"
                        role="radio"
                        className="bed-chip"
                        data-bed={b}
                        aria-checked={form.bed === b}
                        aria-label={holder ? `${b}, occupied by ${holder}` : `${b}, free`}
                        title={holder ? `Occupied by ${holder}` : undefined}
                        disabled={!!holder}
                        tabIndex={b === tabBed ? 0 : -1}
                        onClick={() => set("bed", b)}
                        onKeyDown={(e) => onBedKey(e, b)}
                      >
                        {b}
                        <small>{holder ? "Occupied" : "Free"}</small>
                      </button>
                    );
                  })}
                </div>
              ) : <div className="field-hint">Select a ward first. Its beds appear here, with occupied beds greyed out.</div>}
              {err("bed")}
            </div>
            <div className="form-span">
              <Field label="Reason for admission" htmlFor="adm-reason" required error={errors.reason}>
                <textarea id="adm-reason" className={`textarea small ${errors.reason ? "invalid" : ""}`} value={form.reason} onChange={(e) => set("reason", e.target.value)} placeholder="Presenting problem and why admission is needed" />
              </Field>
            </div>
            <div className="form-span">
              <Field label="Relevant clinical information" htmlFor="adm-notes">
                <textarea id="adm-notes" className="textarea small" value={form.notes} onChange={(e) => set("notes", e.target.value)} placeholder="Optional. Entered by the clinician; nothing is generated." />
              </Field>
            </div>
          </div>
        </Panel>
      </div>

      <div className="adm-actionbar">
        {notice ? <Banner tone="success" role="status">{notice}</Banner> : null}
        {errorCount ? <div className="error-box">{errorCount === 1 ? "1 item needs" : `${errorCount} items need`} attention before the patient can be admitted. Each one is marked above.</div> : null}
        <div className="adm-actionbar-row">
          <span className="small muted">Required: patient, ward, free bed, attending, time, reason and allergy verification.</span>
          {DEMO_MODE ? (
            <button className="btn btn-primary" onClick={submit}>Record admission (preview)</button>
          ) : (
            <button className="btn btn-primary" disabled title="Needs the encounter API (planned)">Admit patient</button>
          )}
        </div>
      </div>
    </div>
  );
}
