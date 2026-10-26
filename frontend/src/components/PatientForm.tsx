import { useState } from "react";
import { Modal } from "./Modal";
import { PREVIEW_SESSION_NOTE } from "../demo/config";
import type { PreviewPatient } from "../demo/previewStore";

export type PatientInput = Omit<PreviewPatient, "id" | "mrn" | "createdAt">;

const BLOOD_GROUPS = ["", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"];
const PHONE = /^\+?[0-9][0-9 -]{6,17}$/;

function splitList(value: string) {
  return value.split(/[,;\n]/).map((item) => item.trim()).filter(Boolean);
}

export function validatePatient(form: Record<string, any>, today: Date) {
  const errors: Record<string, string> = {};
  if (!form.name || form.name.trim().length < 2) errors.name = "Enter the patient's full name.";
  if (!form.sex) errors.sex = "Select a sex.";
  if (!form.dob) errors.dob = "Enter the date of birth.";
  else {
    const dob = new Date(form.dob);
    if (Number.isNaN(dob.getTime())) errors.dob = "Enter a valid date.";
    else if (dob > today) errors.dob = "Date of birth cannot be in the future.";
    else if (today.getFullYear() - dob.getFullYear() > 120) errors.dob = "Check the year of birth.";
  }
  if (!form.phone || !PHONE.test(form.phone.trim())) errors.phone = "Enter a phone number (7–18 digits).";
  if (form.emergencyPhone && !PHONE.test(form.emergencyPhone.trim())) errors.emergencyPhone = "Enter a valid phone number.";
  if (!form.nkda && !splitList(form.allergies || "").length) errors.allergies = "Record allergies, or confirm “No known drug allergies”.";
  return errors;
}

export function PatientForm({
  title,
  initial,
  submitLabel,
  existing,
  onCancel,
  onSubmit,
}: {
  title: string;
  initial?: PreviewPatient;
  submitLabel: string;
  existing: { name: string; dob?: string; id: string }[];
  onCancel: () => void;
  onSubmit: (input: PatientInput) => void;
}) {
  const [form, setForm] = useState<Record<string, any>>(() => ({
    name: initial?.name || "",
    sex: initial?.sex || "",
    dob: initial?.dob || "",
    phone: initial?.phone || "",
    address: initial?.address || "",
    emergencyName: initial?.emergencyName || "",
    emergencyPhone: initial?.emergencyPhone || "",
    bloodGroup: initial?.bloodGroup || "",
    nkda: initial ? initial.allergies.length === 0 : false,
    allergies: initial?.allergies.join(", ") || "",
    problems: initial?.problems.join(", ") || "",
  }));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [touched, setTouched] = useState(false);

  const update = (key: string, value: any) => {
    const next = { ...form, [key]: value };
    setForm(next);
    if (touched) setErrors(validatePatient(next, new Date()));
  };

  function submit() {
    setTouched(true);
    const found = validatePatient(form, new Date());
    const duplicate = existing.find(
      (p) => p.id !== initial?.id && p.name.trim().toLowerCase() === form.name.trim().toLowerCase() && (!p.dob || p.dob === form.dob),
    );
    if (duplicate && !found.name) found.name = "A patient with this name and date of birth is already listed. Check for a duplicate.";
    setErrors(found);
    if (Object.keys(found).length) return;
    onSubmit({
      name: form.name.trim(),
      sex: form.sex,
      dob: form.dob,
      phone: form.phone.trim(),
      address: form.address.trim(),
      emergencyName: form.emergencyName.trim(),
      emergencyPhone: form.emergencyPhone.trim(),
      bloodGroup: form.bloodGroup,
      allergies: form.nkda ? [] : splitList(form.allergies),
      problems: splitList(form.problems),
    });
  }

  const field = (key: string, label: string, required: boolean, input: JSX.Element) => (
    <div className="form-field">
      <label className="field-label" htmlFor={`pf-${key}`}>{label}{required ? <span className="req"> *</span> : null}</label>
      {input}
      {errors[key] ? <div className="field-error" role="alert">{errors[key]}</div> : null}
    </div>
  );

  return (
    <Modal
      title={title}
      onClose={onCancel}
      width={720}
      footer={<><button className="btn" onClick={onCancel}>Cancel</button><button className="btn btn-primary" onClick={submit}>{submitLabel}</button></>}
    >
      <div className="banner warning mb-3">{PREVIEW_SESSION_NOTE}</div>
      <div className="form-grid">
        {field("name", "Full name", true, <input id="pf-name" className={`input ${errors.name ? "invalid" : ""}`} value={form.name} onChange={(e) => update("name", e.target.value)} autoFocus />)}
        {field("sex", "Sex", true, (
          <select id="pf-sex" className={`select ${errors.sex ? "invalid" : ""}`} value={form.sex} onChange={(e) => update("sex", e.target.value)}>
            <option value="">Select…</option><option>Female</option><option>Male</option><option>Other</option>
          </select>
        ))}
        {field("dob", "Date of birth", true, <input id="pf-dob" type="date" className={`input ${errors.dob ? "invalid" : ""}`} value={form.dob} onChange={(e) => update("dob", e.target.value)} />)}
        {field("phone", "Phone", true, <input id="pf-phone" className={`input ${errors.phone ? "invalid" : ""}`} value={form.phone} onChange={(e) => update("phone", e.target.value)} placeholder="+91 98765 43210" />)}
        <div className="form-span">{field("address", "Address", false, <input id="pf-address" className="input" value={form.address} onChange={(e) => update("address", e.target.value)} />)}</div>
        {field("emergencyName", "Emergency contact", false, <input id="pf-emergencyName" className="input" value={form.emergencyName} onChange={(e) => update("emergencyName", e.target.value)} />)}
        {field("emergencyPhone", "Emergency contact phone", false, <input id="pf-emergencyPhone" className={`input ${errors.emergencyPhone ? "invalid" : ""}`} value={form.emergencyPhone} onChange={(e) => update("emergencyPhone", e.target.value)} />)}
        {field("bloodGroup", "Blood group", false, (
          <select id="pf-bloodGroup" className="select" value={form.bloodGroup} onChange={(e) => update("bloodGroup", e.target.value)}>
            {BLOOD_GROUPS.map((g) => <option key={g} value={g}>{g || "Not recorded"}</option>)}
          </select>
        ))}
        <div className="form-span">
          {field("allergies", "Allergies", true, (
            <>
              <label className="check-inline"><input type="checkbox" className="checkbox" checked={form.nkda} onChange={(e) => update("nkda", e.target.checked)} /> No known drug allergies</label>
              <input id="pf-allergies" className={`input mt-1 ${errors.allergies ? "invalid" : ""}`} disabled={form.nkda} value={form.nkda ? "" : form.allergies} onChange={(e) => update("allergies", e.target.value)} placeholder="Substance: reaction, separated by commas" />
            </>
          ))}
        </div>
        <div className="form-span">{field("problems", "Known problems", false, <input id="pf-problems" className="input" value={form.problems} onChange={(e) => update("problems", e.target.value)} placeholder="e.g. Type 2 diabetes, hypertension" />)}</div>
      </div>
    </Modal>
  );
}
