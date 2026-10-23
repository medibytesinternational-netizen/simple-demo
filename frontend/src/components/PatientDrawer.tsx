import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { get } from "../api";
import type { DocumentSummary } from "../types";

type DocumentRecord = DocumentSummary & { image_url?: string | null };
import { DEMO_MODE, PREVIEW_SESSION_NOTE } from "../demo/config";
import { previewStore, usePreviewState } from "../demo/previewStore";
import { Modal } from "./Modal";
import type { DirectoryRow } from "./patientDirectory";
import { CHART_PATIENT_ID } from "./patientDirectory";

const MAX_UPLOAD = 12 * 1024 * 1024;
const DOC_TYPES = ["Lab report", "Imaging report", "Referral letter", "Discharge summary (external)", "Consent form", "Other"];

function fmtSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function fmtDate(value?: string | null) {
  return value ? new Date(value).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
}

export function PatientDrawer({ row, onClose, onEdit }: { row: DirectoryRow; onClose: () => void; onEdit?: () => void }) {
  const [tab, setTab] = useState<"summary" | "documents" | "encounter">("summary");
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer drawer-wide" role="dialog" aria-modal="true" aria-label={`Patient details: ${row.name}`}>
        <div className="drawer-head">
          <div className="flex items-center gap-3">
            <span className="avatar avatar-soft">{row.name.split(" ").map((p) => p[0]).join("").slice(0, 2)}</span>
            <div>
              <div className="card-title">{row.name} {row.source === "preview" ? <span className="badge badge-warning">preview record</span> : null}</div>
              <div className="small muted">{row.mrn} · {row.age ?? "—"} y · {row.sex}</div>
            </div>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>Close</button>
        </div>
        <div className="tabs drawer-tabs" role="tablist">
          {(["summary", "documents", "encounter"] as const).map((key) => (
            <button key={key} role="tab" aria-selected={tab === key} className={`tab ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>
              {key === "summary" ? "Summary" : key === "documents" ? "Documents" : "Encounter"}
            </button>
          ))}
        </div>
        <div className="drawer-body">
          {tab === "summary" ? <Summary row={row} onEdit={onEdit} /> : null}
          {tab === "documents" ? <Documents row={row} /> : null}
          {tab === "encounter" ? <Encounter row={row} /> : null}
        </div>
      </aside>
    </>
  );
}

function Summary({ row, onEdit }: { row: DirectoryRow; onEdit?: () => void }) {
  const p = row.previewPatient;
  return (
    <div className="flex-col gap-3">
      <div className={`allergy-panel ${row.allergies.length || !row.allergiesKnown ? "" : "none"}`}>
        <div className="section-label" style={{ margin: 0 }}>Allergies</div>
        <div className="fs-13 mt-1">{row.allergies.length ? row.allergies.join(", ") : row.allergiesKnown ? "No known drug allergies recorded" : "Allergy record not available in this view. Check the hospital record before prescribing."}</div>
      </div>
      <dl className="kv">
        <dt>MRN</dt><dd className="mono">{row.mrn}</dd>
        <dt>Age / sex</dt><dd>{row.age ?? "—"} · {row.sex}</dd>
        {p ? <><dt>Date of birth</dt><dd>{p.dob}</dd><dt>Phone</dt><dd>{p.phone}</dd><dt>Address</dt><dd>{p.address || "—"}</dd>
          <dt>Emergency contact</dt><dd>{p.emergencyName ? `${p.emergencyName}${p.emergencyPhone ? ` · ${p.emergencyPhone}` : ""}` : "—"}</dd>
          <dt>Blood group</dt><dd>{p.bloodGroup || "Not recorded"}</dd></> : null}
        <dt>Problems</dt><dd>{row.problems.length ? row.problems.join(" · ") : "None recorded"}</dd>
        <dt>Encounter</dt><dd>{row.status === "active" ? `${row.kind || ""} · ${row.ward} · ${row.bed}` : row.status}</dd>
        {row.source === "seed" ? <><dt>Open alerts</dt><dd>{row.openAlerts} ({row.criticalAlerts} critical)</dd><dt>Overdue tasks</dt><dd>{row.overdueTasks}</dd></> : null}
      </dl>
      {row.chartAvailable ? (
        <Link className="btn btn-primary" to="/timeline">Open full clinical chart</Link>
      ) : (
        <div className="banner">
          {row.source === "preview"
            ? "Preview patient — no clinical records exist. Notes, medications, labs and alerts are not shown because none have been documented."
            : "Summary only. A full clinical chart for this patient needs patient-scoped APIs, which are not available yet."}
        </div>
      )}
      <div className="button-row">
        {onEdit ? <button className="btn" onClick={onEdit}>Edit patient details</button> : (
          <button className="btn" disabled title={DEMO_MODE ? "Only preview records can be edited in the UI preview" : "Patient editing needs the patient API (planned)"}>Edit patient details</button>
        )}
        <Link className="btn" to={`/admission?patient=${encodeURIComponent(row.id)}`}>Admission…</Link>
      </div>
    </div>
  );
}

type DocRow = { id: string; filename: string; type: string; when?: string | null; status: string; url?: string | null; size?: number; preview?: boolean; archived?: { reason: string; at: string } };

function Documents({ row }: { row: DirectoryRow }) {
  const preview = usePreviewState();
  const [docType, setDocType] = useState(DOC_TYPES[0]);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [archiving, setArchiving] = useState<DocRow | null>(null);
  const [reason, setReason] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const input = useRef<HTMLInputElement | null>(null);
  const seedDocs = useQuery<{ documents: DocumentRecord[] }>({
    queryKey: ["documents"],
    queryFn: () => get("/documents"),
    enabled: row.id === CHART_PATIENT_ID,
  });

  const rows: DocRow[] = [
    ...(row.id === CHART_PATIENT_ID ? (seedDocs.data?.documents || []).map((d) => ({
      id: d.id, filename: d.filename, type: d.doc_type.replaceAll("_", " "), when: d.uploaded_at, status: d.ocr_status.replaceAll("_", " "), url: d.image_url,
    })) : []),
    ...(DEMO_MODE ? preview.documents.filter((d) => d.patientId === row.id).map((d) => ({
      id: d.id, filename: d.filename, type: d.docType, when: d.uploadedAt, status: d.archived ? "archived" : "preview upload", url: d.url, size: d.size, preview: true, archived: d.archived,
    })) : []),
  ];
  const visible = rows.filter((d) => showArchived || !d.archived);

  function onFile(file?: File | null) {
    if (!file) return;
    if (file.size > MAX_UPLOAD) {
      setMessage({ kind: "error", text: `“${file.name}” is ${fmtSize(file.size)}. The limit is 12 MB.` });
      return;
    }
    previewStore.addDocument(row.id, file, docType);
    setMessage({ kind: "success", text: `“${file.name}” added to this preview tab. It is not uploaded or stored anywhere.` });
    if (input.current) input.current.value = "";
  }

  return (
    <div className="flex-col gap-3">
      {DEMO_MODE ? <div className="banner warning">{PREVIEW_SESSION_NOTE}</div> : null}
      <div className="upload-row">
        <select className="select select-compact" value={docType} onChange={(e) => setDocType(e.target.value)} aria-label="Document type" disabled={!DEMO_MODE}>
          {DOC_TYPES.map((t) => <option key={t}>{t}</option>)}
        </select>
        <input ref={input} type="file" className="sr-only" id="doc-upload" onChange={(e) => onFile(e.target.files?.[0])} disabled={!DEMO_MODE} accept=".pdf,.png,.jpg,.jpeg,.svg,.txt,.doc,.docx" />
        <label htmlFor="doc-upload" className={`btn ${DEMO_MODE ? "btn-primary" : "disabled-label"}`} aria-disabled={!DEMO_MODE}>Upload document</label>
        {!DEMO_MODE ? <span className="small muted">Patient document upload needs the patient documents API (planned).</span> : null}
      </div>
      {message ? <div className={message.kind === "success" ? "success-box" : "error-box"} role="status">{message.text}</div> : null}
      {seedDocs.isLoading ? <div className="loading">Loading documents…</div> : null}
      {seedDocs.isError ? <div className="error-box">Could not load documents: {(seedDocs.error as Error).message}</div> : null}
      {!visible.length && !seedDocs.isLoading ? (
        <div className="empty"><div className="empty-title">No documents</div>{row.id === CHART_PATIENT_ID || DEMO_MODE ? "Nothing on file for this patient yet." : "Documents for this patient need patient-scoped APIs."}</div>
      ) : null}
      {visible.length ? (
        <table className="table">
          <thead><tr><th>Document</th><th>Type</th><th>Added</th><th>Status</th><th className="right">Actions</th></tr></thead>
          <tbody>
            {visible.map((d) => (
              <tr key={d.id} className={d.archived ? "row-archived" : ""}>
                <td><div className="cell-strong">{d.filename}</div>{d.size ? <div className="cell-sub">{fmtSize(d.size)}</div> : null}{d.archived ? <div className="cell-sub">Archived: {d.archived.reason}</div> : null}</td>
                <td>{d.type}</td>
                <td className="nowrap">{fmtDate(d.when)}</td>
                <td><span className={`badge ${d.preview ? "badge-warning" : "badge-neutral"}`}>{d.status}</span></td>
                <td className="right nowrap">
                  {d.url ? <a className="btn btn-sm" href={d.url} target="_blank" rel="noreferrer">View</a> : null}
                  {d.url ? <a className="btn btn-sm" href={d.url} download={d.filename}>Download</a> : null}
                  {d.preview && !d.archived ? <button className="btn btn-sm btn-danger" onClick={() => { setArchiving(d); setReason(""); }}>Archive…</button> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {rows.some((d) => d.archived) ? (
        <label className="check-inline small"><input type="checkbox" className="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Show archived documents</label>
      ) : null}
      {archiving ? (
        <Modal
          title="Archive document"
          onClose={() => setArchiving(null)}
          footer={<>
            <button className="btn" onClick={() => setArchiving(null)}>Cancel</button>
            <button className="btn btn-danger" disabled={reason.trim().length < 5} onClick={() => { previewStore.archiveDocument(archiving.id, reason.trim()); setArchiving(null); setMessage({ kind: "success", text: "Document archived in this preview tab. Nothing was deleted or stored." }); }}>Archive</button>
          </>}
        >
          <p className="fs-13" style={{ marginTop: 0 }}>Archive “{archiving.filename}”? Archived documents stay viewable; nothing is permanently deleted.</p>
          <label className="field-label" htmlFor="archive-reason">Reason (required)</label>
          <textarea id="archive-reason" className="textarea small" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is this document being archived?" />
          <div className="small muted mt-1">At least 5 characters.</div>
        </Modal>
      ) : null}
    </div>
  );
}

function Encounter({ row }: { row: DirectoryRow }) {
  const enc = row.previewEncounter;
  if (enc) {
    return (
      <div className="flex-col gap-3">
        <div className="banner warning">Preview admission — recorded in this browser tab only. No encounter was created in any hospital system.</div>
        <dl className="kv">
          <dt>Type</dt><dd>{enc.kind}</dd><dt>Ward / bed</dt><dd>{enc.ward} · {enc.bed}</dd><dt>Attending</dt><dd>{enc.attending}</dd>
          <dt>Admitted</dt><dd>{fmtDate(enc.admittedAt)}</dd><dt>Reason</dt><dd>{enc.reason}</dd>
          <dt>Clinical notes</dt><dd>{enc.notes || "—"}</dd><dt>Allergy record checked by</dt><dd>{enc.allergyCheckedBy}</dd>
        </dl>
      </div>
    );
  }
  if (row.status === "active") {
    return <dl className="kv"><dt>Type</dt><dd>{row.kind}</dd><dt>Ward / bed</dt><dd>{row.ward} · {row.bed}</dd><dt>Status</dt><dd>active</dd></dl>;
  }
  return (
    <div className="flex-col gap-3">
      <div className="empty"><div className="empty-title">{row.status === "discharged" ? "Most recent encounter discharged" : "Not admitted"}</div>No active encounter for this patient.</div>
      <Link className="btn btn-primary" to={`/admission?patient=${encodeURIComponent(row.id)}`}>Start admission</Link>
    </div>
  );
}
