import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, intakeAudio, intakeDocument, openStoredFile, post, session, type Intake } from "../api";
import type { Meta } from "../types";
import { VoiceInput } from "../components/VoiceInput";
import { OPD_HEARD_SECTIONS } from "../features/f01/opdFormat";
import { useCan } from "../session";
import { DEMO_MODE, PREVIEW_WRITE_MESSAGE } from "../demo/config";

const MAX_REPORT_BYTES = 12 * 1024 * 1024;

type Registered = {
  patient: { id: string; mrn: string; name: string };
  encounter: { id: string };
  attached: { intake_id: string; kind: "audio" | "document"; draft_id?: string; document_id?: string }[];
};
type Saved = { patientId: string; name: string; mrn: string; noteDocumentId?: string | null; toCheck: string[] };

type Details = { name: string; age: string; sex: string; phone: string; allergies: string; nkda: boolean; problems: string };
const EMPTY: Details = { name: "", age: "", sex: "", phone: "", allergies: "", nkda: false, problems: "" };

const listOf = (value: string) => value.split(/[,;\n]/).map((x) => x.trim()).filter(Boolean);
const text = (v: any): string => (v && typeof v === "object" ? String(v.text ?? "") : String(v ?? "")).trim();

/** Merge what one recording or document found into the details. Values typed by hand stay. */
function merge(current: Details, sources: Record<string, string>, typed: Set<string>, item: Intake) {
  const next = { ...current };
  const from = { ...sources };
  const label = item.kind === "audio" ? "recording" : item.filename;
  const set = (key: keyof Details, value: any, sourceKey: string) => {
    if (typed.has(key) || value === undefined || value === null || value === "") return;
    (next as any)[key] = value;
    from[key] = `${label}: "${item.fields[sourceKey]?.source || ""}"`;
  };
  const f = item.fields || {};
  // A title is not part of the name.
  set("name", typeof f.name?.value === "string" ? f.name.value.replace(/^(mrs|mr|ms|miss|master|dr|smt|shri)\.?\s+/i, "").trim() : undefined, "name");
  set("age", f.age?.value != null ? String(f.age.value) : undefined, "age");
  set("sex", f.sex?.value, "sex");
  set("phone", f.phone?.value, "phone");
  if (f.no_known_allergies?.value === true) {
    set("nkda", true, "no_known_allergies");
    if (!typed.has("allergies")) next.allergies = "";
  } else if (Array.isArray(f.allergies?.value) && f.allergies.value.length) {
    set("allergies", [...new Set([...listOf(current.allergies), ...f.allergies.value])].join(", "), "allergies");
    if (!typed.has("nkda")) next.nkda = false;
  }
  if (Array.isArray(f.problems?.value) && f.problems.value.length) {
    set("problems", [...new Set([...listOf(current.problems), ...f.problems.value])].join(", "), "problems");
  }
  return { next, from };
}

function validate(d: Details) {
  const errors: Partial<Record<keyof Details, string>> = {};
  if (d.name.trim().length < 2) errors.name = "Enter the full name.";
  if (!/^\d{1,3}$/.test(d.age.trim()) || Number(d.age) > 130) errors.age = "Enter the age in years.";
  if (!d.sex) errors.sex = "Select the sex.";
  if (d.phone.trim() && !/^\+?[0-9][0-9 -]{6,17}$/.test(d.phone.trim())) errors.phone = "Check the phone number.";
  if (!d.nkda && !listOf(d.allergies).length) errors.allergies = "Record allergies, or tick no known drug allergies.";
  return errors;
}

/**
 * New patient on one screen: record or upload the consultation and the old documents, read the
 * OPD report straight away below, check it, and sign and save. Saving registers the patient, signs
 * the OPD note and adds the documents' values to the record.
 */
export function NewPatientPage() {
  const queryClient = useQueryClient();
  const canRegister = useCan("register_patient");
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta") });
  const [intakes, setIntakes] = useState<Intake[]>([]);
  const [details, setDetails] = useState<Details>(EMPTY);
  const [sources, setSources] = useState<Record<string, string>>({});
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [tried, setTried] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<Saved | null>(null);
  // Latest values for reads that finish one after another (several documents, then a recording).
  const live = useRef({ details: EMPTY, sources: {} as Record<string, string>, typed: new Set<string>() });

  const added = (item: Intake) => {
    setIntakes((list) => [...list.filter((x) => x.intake_id !== item.intake_id), item]);
    const { next, from } = merge(live.current.details, live.current.sources, live.current.typed, item);
    live.current.details = next;
    live.current.sources = from;
    setDetails(next);
    setSources(from);
  };
  const edit = (key: keyof Details, value: any) => {
    const next = { ...live.current.details, [key]: value };
    const typed = new Set(live.current.typed).add(key);
    const { [key]: _gone, ...rest } = live.current.sources;
    live.current = { details: next, sources: rest, typed };
    setDetails(next);
    setSources(rest);
  };
  const reset = () => {
    live.current = { details: EMPTY, sources: {}, typed: new Set() };
    setIntakes([]); setDetails(EMPTY); setSources({}); setConsent(false); setTried(false); setSaved(null); setError("");
  };

  const readDocuments = async (files: FileList | null) => {
    const list = Array.from(files || []);
    setError("");
    for (const [i, file] of list.entries()) {
      if (file.size > MAX_REPORT_BYTES) { setError(`${file.name} is too large (max 12 MB).`); continue; }
      setBusy(`Reading ${file.name} (${i + 1} of ${list.length})...`);
      try {
        added(await intakeDocument(file, "auto"));
      } catch (e: any) {
        setError(`${file.name}: ${String(e?.message || e)}`);
      }
    }
    setBusy("");
  };

  const errors = validate(details);
  const save = async () => {
    setTried(true);
    if (Object.keys(errors).length) return;
    setError("");
    setSaving(true);
    try {
      const result = await post<Registered>("/patients", {
        name: details.name.trim(),
        age: Number(details.age),
        sex: details.sex,
        phone: details.phone.trim() || null,
        allergies: details.nkda ? [] : listOf(details.allergies),
        no_known_allergies: details.nkda,
        problems: listOf(details.problems),
        intake_ids: intakes.filter((x) => x.status === "ready").map((x) => x.intake_id),
      });
      // Everything after this is about the new patient.
      session.setPatient(result.patient.id);
      let noteDocumentId: string | null | undefined;
      const toCheck: string[] = [];
      for (const item of result.attached) {
        if (item.kind === "audio" && item.draft_id) {
          // The clinician has read the report on this screen; Sign and save signs it.
          const signed = await post<{ event: { document_id?: string | null } }>(`/drafts/${item.draft_id}/approve`, {});
          noteDocumentId = signed.event?.document_id;
        }
        if (item.kind === "document" && item.document_id) {
          const doc = await get<{ ocr_status: string; filename: string }>(`/documents/${item.document_id}`);
          if (doc.ocr_status === "reviewed") await post(`/documents/${item.document_id}/commit`);
          else toCheck.push(doc.filename);
        }
      }
      queryClient.clear();
      setSaved({ patientId: result.patient.id, name: result.patient.name, mrn: result.patient.mrn, noteDocumentId, toCheck });
    } catch (err: any) {
      setError(err instanceof ApiError && err.status === 409 ? err.message : String(err?.message || err));
    } finally {
      setSaving(false);
    }
  };

  if (DEMO_MODE) {
    return (
      <div className="page npf">
        <PageTitle />
        <section className="his-box"><p className="his-box-empty">{PREVIEW_WRITE_MESSAGE}</p></section>
      </div>
    );
  }

  if (saved) {
    return (
      <div className="page npf">
        <PageTitle />
        <section className="his-box">
          <h2 className="his-box-title">Saved</h2>
          <div className="npf-body">
            <p style={{ marginTop: 0 }}><strong>{saved.name}</strong> ({saved.mrn}) is registered. The OPD report is signed and everything is on the timeline.</p>
            {saved.toCheck.length ? (
              <div className="banner warning mb-3">
                Some values in {saved.toCheck.join(", ")} were unclear. Check them in <Link to="/documents?tab=inbound">Reports</Link> before they are added.
              </div>
            ) : null}
            <div className="button-row">
              <Link className="btn btn-primary" to="/timeline">Open timeline</Link>
              {saved.noteDocumentId ? <button className="btn" onClick={() => openStoredFile(saved.noteDocumentId!).catch((e) => setError(String(e?.message || e)))}>Print OPD report</button> : null}
              <Link className="btn" to="/patient">Patient overview</Link>
              <button className="btn" onClick={reset}>New patient</button>
            </div>
            {error ? <div className="error-box mt-3" role="alert">{error}</div> : null}
          </div>
        </section>
      </div>
    );
  }

  const show = (key: keyof Details) => (tried ? errors[key] : undefined);
  const hint = (key: string) => (sources[key] ? <span className="pf-from" title={sources[key]}>From {sources[key]}</span> : null);
  const cls = (key: string) => `input${sources[key] ? " npf-auto" : ""}`;
  const recording = intakes.find((x) => x.kind === "audio");
  const docs = intakes.filter((x) => x.kind === "document");
  const report = recording?.preview;
  const today = new Date().toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  const me = meta.data?.user?.name || "";

  return (
    <div className="page npf">
      <PageTitle />

      <section className="his-box">
        <h2 className="his-box-title">Recording and documents</h2>
        <div className="npf-body">
          {!canRegister ? <div className="banner warning mb-3">Your role cannot register patients.</div> : null}
          <div className="npf-intake-grid">
            <div className="npf-capture">
              <div className="npf-capture-title">Consultation voice</div>
              <label className="check-inline">
                <input type="checkbox" className="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                The patient consents to recording this consultation
              </label>
              <div className="mt-2">
                <VoiceInput
                  consentGranted={consent}
                  disabled={!!busy || !canRegister || saving}
                  capture={async (audio, filename) => {
                    setError("");
                    setBusy("Transcribing the consultation and writing the OPD report. This usually takes under a minute.");
                    try {
                      added(await intakeAudio(audio, filename));
                    } finally {
                      setBusy("");
                    }
                  }}
                />
              </div>
            </div>
            <div className="npf-capture">
              <div className="npf-capture-title">Previous documents</div>
              <label className={`btn btn-sm${busy || !canRegister || saving ? " is-disabled" : ""}`}>
                Upload documents
                <input type="file" multiple accept="image/*,application/pdf" style={{ display: "none" }} disabled={!!busy || !canRegister || saving}
                  onChange={(e) => { void readDocuments(e.target.files); e.target.value = ""; }} />
              </label>
              <div className="small muted mt-1">Old prescriptions, discharge summaries or reports. PDF or photo; choose several at once.</div>
            </div>
          </div>
          {busy ? <div className="banner mt-3" role="status"><span className="spinner" /> {busy}</div> : null}
          {error ? <div className="error-box mt-3" role="alert">{error}</div> : null}
        </div>
      </section>

      <section className="his-box npf-report">
        <h2 className="his-box-title">OPD report</h2>
        <div className="npf-body">
          <div className="npf-capture-title">Patient record {Object.keys(sources).length ? <span className="muted small">(yellow = filled automatically; check it)</span> : null}</div>
          <div className="npf-details-grid">
            <label>Patient name *<input className={cls("name")} value={details.name} onChange={(e) => edit("name", e.target.value)} />{show("name") ? <span className="field-error">{show("name")}</span> : hint("name")}</label>
            <label>Age (years) *<input className={cls("age")} inputMode="numeric" value={details.age} onChange={(e) => edit("age", e.target.value.replace(/[^0-9]/g, ""))} />{show("age") ? <span className="field-error">{show("age")}</span> : hint("age")}</label>
            <label>Sex *
              <select className={`select${sources.sex ? " npf-auto" : ""}`} value={details.sex} onChange={(e) => edit("sex", e.target.value)}>
                <option value="">Select...</option><option>Female</option><option>Male</option><option>Other</option>
              </select>{show("sex") ? <span className="field-error">{show("sex")}</span> : hint("sex")}
            </label>
            <label>Phone<input className={cls("phone")} value={details.phone} onChange={(e) => edit("phone", e.target.value)} />{show("phone") ? <span className="field-error">{show("phone")}</span> : hint("phone")}</label>
            <label className="npf-wide">Allergies *
              <input className={cls("allergies")} value={details.nkda ? "" : details.allergies} disabled={details.nkda} onChange={(e) => edit("allergies", e.target.value)} placeholder="Substance: reaction, separated by commas" />
              <span className="check-inline"><input type="checkbox" className="checkbox" checked={details.nkda} onChange={(e) => edit("nkda", e.target.checked)} /> No known drug allergies</span>
              {show("allergies") ? <span className="field-error">{show("allergies")}</span> : hint(details.nkda ? "nkda" : "allergies")}
            </label>
            <label className="npf-wide">Known problems<input className={cls("problems")} value={details.problems} onChange={(e) => edit("problems", e.target.value)} />{hint("problems")}</label>
          </div>
          <dl className="opd-record mt-3">
            <div><dt>Date of admission</dt><dd>{today}</dd></div>
            <div><dt>Hospital number</dt><dd>Given on saving</dd></div>
            <div><dt>Department</dt><dd>Outpatient department (OPD)</dd></div>
            <div><dt>Unit and consultant</dt><dd>{me || "-"}</dd></div>
            <div><dt>History and physical recorded by</dt><dd>{me || "-"}</dd></div>
          </dl>

          {report ? (
            <div className="npf-opd mt-3">
              {OPD_HEARD_SECTIONS.map(([key, label, many]) => {
                const items = (many ? report[key] || [] : [report[key]]).map(text).filter(Boolean);
                return (
                  <div key={key} className="npf-opd-row">
                    <div className="npf-opd-label">{label}</div>
                    <div className="npf-opd-value">
                      {items.length ? (items.length > 1 ? <ul>{items.map((t: string, i: number) => <li key={i}>{t}</li>)}</ul> : items[0]) : <span className="muted">Not documented</span>}
                    </div>
                  </div>
                );
              })}
              {report.needs_review?.length ? (
                <div className="banner warning mt-2">
                  Check these against the recording: {report.needs_review.map((r: any) => `${r.section}: ${r.text}`).join("; ")}
                </div>
              ) : null}
            </div>
          ) : (
            <p className="small muted mt-3">The heard part of the report (complaints, history, allergies, pain...) appears here as soon as the consultation voice is read.</p>
          )}

          {docs.length ? (
            <div className="mt-3">
              <div className="npf-capture-title">Previous documents</div>
              {docs.map((d) => (
                <div key={d.intake_id} className="npf-doc mt-2">
                  <div className="npf-doc-head">
                    <div className="npf-doc-name"><strong>{d.filename}</strong><span className="muted small">{d.doc_type === "prescription" ? "Prescription" : "Discharge summary"}</span></div>
                  </div>
                  {d.values?.length ? (
                    <table className="table mt-2">
                      <tbody>{d.values.map((v, i) => <tr key={i}><td>{v.name}</td><td className="strong">{[v.value, v.unit].filter(Boolean).join(" ")}</td><td className="muted small">{v.reference_range}</td></tr>)}</tbody>
                    </table>
                  ) : <p className="small muted">No values read; the document is kept in the record.</p>}
                </div>
              ))}
            </div>
          ) : null}

          <div className="button-row mt-3">
            <Link className="btn" to="/patients">Cancel</Link>
            <button className="btn btn-primary" onClick={save} disabled={!canRegister || saving || !!busy}>
              {saving ? <><span className="spinner" /> Saving...</> : report ? "Sign and save to record" : "Save to record"}
            </button>
            <span className="small muted">{report ? "Saving registers the patient and signs this OPD report as you." : "Registers the patient and keeps the documents."}</span>
          </div>
        </div>
      </section>
    </div>
  );
}

function PageTitle() {
  return (
    <header className="page-header">
      <div className="page-header-text">
        <h1 className="page-h1">New patient</h1>
        <p className="page-desc">Record the consultation and upload old documents. The OPD report is written below; check it, then sign and save.</p>
      </div>
    </header>
  );
}
