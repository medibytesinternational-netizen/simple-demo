import { useEffect, useState } from "react";
import { openStoredFile, storedFileUrl } from "../../api";
import { DEMO_MODE } from "../../demo/config";
import type { TimelineEventF16 } from "./types";
import { OPD_HEARD_SECTIONS, isOpdV2 } from "../f01/opdFormat";
import { ADMIT_HEARD_SECTIONS, isAdmitV2 } from "../f02/admitFormat";

const text = (value: any): string => (value && typeof value === "object" ? String(value.text ?? "") : String(value ?? "")).trim();

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="evb-row"><span className="evb-label">{label}</span><span className="evb-value">{children}</span></div>;
}

/** The stored file behind an event: open it inline, or in a new tab to print. */
function StoredDocument({ documentId, label }: { documentId: string; label: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  const toggle = async () => {
    setError("");
    if (open) { setOpen(false); return; }
    try {
      if (!url) setUrl(await storedFileUrl(documentId));
      setOpen(true);
    } catch (e: any) {
      setError(String(e?.message || e));
    }
  };
  if (DEMO_MODE) return null;
  return (
    <div className="evb-doc">
      <div className="button-row">
        <button type="button" className="btn btn-sm" onClick={toggle} aria-expanded={open}>{open ? `Hide ${label}` : `View ${label}`}</button>
        <button type="button" className="btn btn-sm" onClick={() => openStoredFile(documentId).catch((e) => setError(String(e?.message || e)))}>Print / open</button>
      </div>
      {error ? <div className="error-box mt-1" role="alert">{error}</div> : null}
      {open && url ? <iframe className="evb-frame" src={url} title={label} sandbox="allow-modals allow-same-origin allow-scripts" /> : null}
    </div>
  );
}

function OpdNote({ p }: { p: any }) {
  const h = p.header || {};
  return (
    <div className="evb">
      <Row label="Patient">{[h.patient_name, h.age_sex, h.hospital_number].filter(Boolean).join(" · ")}</Row>
      <Row label="Visit">{[h.department, h.date_of_admission, h.unit_consultant].filter(Boolean).join(" · ")}</Row>
      {OPD_HEARD_SECTIONS.map(([key, label, many]) => {
        const items = (many ? p[key] || [] : [p[key]]).map(text).filter(Boolean);
        if (!items.length) return null;
        return <Row key={key} label={label.replace(/ \(.*\)$/, "")}>{items.length > 1 ? <ul>{items.map((t: string, i: number) => <li key={i}>{t}</li>)}</ul> : items[0]}</Row>;
      })}
      {h.recorded_by ? <Row label="Recorded by">{h.recorded_by}</Row> : null}
    </div>
  );
}

function AdmissionNote({ p }: { p: any }) {
  const h = p.header || {};
  return (
    <div className="evb">
      <Row label="Patient">{[h.name, h.sex, h.age, h.op_number].filter(Boolean).join(" · ")}</Row>
      <Row label="Admitted">{[h.date_of_admission, h.consultant ? `under ${h.consultant}` : ""].filter(Boolean).join(" ")}</Row>
      {ADMIT_HEARD_SECTIONS.map(([key, label, many]) => {
        const raw = many ? p[key] || [] : p[key] ? [p[key]] : [];
        const items = raw.map((c: any) => text(c) + (c?.origin === "opd" ? " (from OPD report)" : "")).filter((t: string) => t.trim());
        if (!items.length) return null;
        return <Row key={key} label={label.replace(/ \(.*\)$/, "")}>{items.length > 1 ? <ul>{items.map((t: string, i: number) => <li key={i}>{t}</li>)}</ul> : items[0]}</Row>;
      })}
    </div>
  );
}

function ConsultNote({ p }: { p: any }) {
  if (isOpdV2(p)) return <OpdNote p={p} />;
  const assessment = (p.assessment || []).map(text).filter(Boolean);
  const plan = (p.plan || []).map(text).filter(Boolean);
  const meds = (p.medication_mentions || []).filter((m: any) => m?.drug);
  const exam = [text(p.exam?.general), text(p.exam?.systemic)].filter(Boolean).join(" ");
  return (
    <div className="evb">
      {text(p.chief_complaint) ? <Row label="Complaint">{text(p.chief_complaint)}</Row> : null}
      {text(p.hpi) ? <Row label="History">{text(p.hpi)}</Row> : null}
      {exam ? <Row label="Exam">{exam}</Row> : null}
      {assessment.length ? <Row label="Assessment"><ul>{assessment.map((a: string, i: number) => <li key={i}>{a}</li>)}</ul></Row> : null}
      {plan.length ? <Row label="Plan"><ul>{plan.map((a: string, i: number) => <li key={i}>{a}</li>)}</ul></Row> : null}
      {meds.length ? <Row label="Medicines">{meds.map((m: any) => [m.drug, m.dose, m.frequency].filter(Boolean).join(" ")).join("; ")}</Row> : null}
      {text(p.follow_up) ? <Row label="Follow-up">{text(p.follow_up)}</Row> : null}
    </div>
  );
}

function LabResult({ p }: { p: any }) {
  const flag = String(p.flag || "");
  const abnormal = flag === "high" || flag === "low";
  return (
    <div className="evb evb-inline">
      <span className={`evb-lab ${abnormal ? "his-tone-critical" : ""}`}><b>{p.name}</b> {p.value} {p.unit}</span>
      {p.reference_range ? <span className="muted">ref {p.reference_range}</span> : null}
      {abnormal ? <span className="evb-flag">{flag.toUpperCase()}</span> : null}
      {p.review_status === "unreviewed" ? <span className="evb-tag">unreviewed</span> : null}
    </div>
  );
}

function MedOrder({ p }: { p: any }) {
  return (
    <div className="evb evb-inline">
      <span><b>{p.drug}</b> {[p.dose, p.route, p.frequency].filter(Boolean).join(" ")}</span>
      <span className="evb-tag">{p.kind === "home" ? "home medicine" : p.kind || "order"}</span>
      {p.status && p.status !== "active" ? <span className="evb-tag">{p.status}</span> : null}
    </div>
  );
}

function DocumentReview({ p }: { p: any }) {
  const fields = (p.fields || []) as any[];
  return (
    <div className="evb">
      <Row label="Report">{String(p.document_type || "").replaceAll("_", " ")} · {p.filename}</Row>
      {fields.length ? (
        <table className="table evb-table">
          <tbody>{fields.map((f, i) => <tr key={i}><td>{f.name}</td><td>{[f.value, f.unit].filter(Boolean).join(" ")}</td></tr>)}</tbody>
        </table>
      ) : null}
    </div>
  );
}

function Registration({ p }: { p: any }) {
  const allergies = p.allergies?.length ? p.allergies.join(", ") : p.no_known_allergies ? "No known drug allergies" : "Not recorded";
  return (
    <div className="evb">
      <Row label="Patient">{p.mrn} · {p.age} y · {p.sex}{p.phone ? ` · ${p.phone}` : ""}</Row>
      <Row label="Allergy"><span className={p.allergies?.length ? "his-tone-critical strong" : ""}>{allergies}</span></Row>
      {p.problems?.length ? <Row label="Problems">{p.problems.join(", ")}</Row> : null}
      <Row label="Visit">{p.visit || "OPD"} visit opened</Row>
    </div>
  );
}

/** One dictated progress-notes row: the notes and who signed them. */
function ProgressEntry({ p }: { p: Record<string, any> }) {
  const notes: string[] = (p.notes || []).map((n: any) => String(n?.text ?? n ?? "").trim()).filter(Boolean);
  return (
    <div className="evb">
      <Row label="Notes">{notes.join("; ")}</Row>
      {p.signed_by?.name ? <Row label="Signed">{p.signed_by.name}{p.signed_by.role ? ` (${p.signed_by.role})` : ""}</Row> : null}
    </div>
  );
}

/** Timeline entry body, formatted by event type. Types without a layout fall back to the plain text. */
export function EventBody({ event }: { event: TimelineEventF16 }) {
  const p = event.payload || {};
  let body: React.ReactNode = null;
  if (event.type === "consult_note") body = <ConsultNote p={p} />;
  else if (event.type === "admission_note" && isAdmitV2(p)) body = <AdmissionNote p={p} />;
  else if (event.type === "lab_result" && p.name) body = <LabResult p={p} />;
  else if (event.type === "med_order" && p.drug) body = <MedOrder p={p} />;
  else if (event.type === "document_review") body = <DocumentReview p={p} />;
  else if (event.type === "registration") body = <Registration p={p} />;
  else if ((event.type === "progress_note" || event.type === "nurse_progress_note") && p.format === "progress_v2") body = <ProgressEntry p={p} />;
  else if (event.body_text) body = <span className="tl-preview">{event.body_text}</span>;

  // Signed OPD reports and admission notes are stored as documents to view and print.
  const storedNote = ["consult_note", "admission_note", "progress_report", "referral", "discharge_report"].includes(event.type) && event.document_id;
  if (!body && !storedNote) return null;
  return (
    <>
      {body}
      {storedNote ? <StoredDocument documentId={event.document_id!} label={event.type === "admission_note" ? "admission note" : event.type === "progress_report" ? "progress notes report" : event.type === "referral" ? "referral form" : event.type === "discharge_report" ? "discharge summary" : "OPD note document"} /> : null}
    </>
  );
}
