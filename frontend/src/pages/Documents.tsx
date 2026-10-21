import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { get, post, uploadDocument } from "../api";
import type { DocumentDetail, DocumentRequest, DocumentSummary, Draft, InvestigationRequest } from "../types";
import { DraftReview } from "../components/DraftReview";

export function DocumentsPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "inbound";
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [matchChoice, setMatchChoice] = useState<Record<string, string>>({});

  const documents = useQuery<{ documents: DocumentSummary[] }>({
    queryKey: ["documents"],
    queryFn: () => get("/documents"),
  });
  const document = useQuery<DocumentDetail>({
    queryKey: ["document", selectedId],
    queryFn: () => get(`/documents/${selectedId}`),
    enabled: Boolean(selectedId),
  });
  const requests = useQuery<{ requests: DocumentRequest[] }>({
    queryKey: ["document-requests"],
    queryFn: () => get("/document-requests"),
    enabled: tab === "followup",
  });
  const investigations = useQuery<{ requests: InvestigationRequest[] }>({
    queryKey: ["investigation-requests"],
    queryFn: () => get("/investigation-requests"),
    enabled: tab === "requisition",
  });
  const drafts = useQuery<{ drafts: Draft[] }>({
    queryKey: ["drafts", "F10"],
    queryFn: () => get("/drafts?feature=F10&limit=1"),
    enabled: tab === "requisition",
  });

  useEffect(() => {
    if (!selectedId && documents.data?.documents?.length) {
      setSelectedId(documents.data.documents[0].id);
    }
  }, [documents.data, selectedId]);

  const upload = useMutation({
    mutationFn: (file: File) => uploadDocument(file),
    onSuccess: (result: any) => {
      setSelectedId(result.id);
      setError("");
      setSuccess("Upload complete. Extraction is ready for review.");
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const confirmField = useMutation({
    mutationFn: ({ index, value }: { index: number; value?: string }) =>
      post(`/documents/${selectedId}/confirm-field`, { index, value }),
    onSuccess: () => {
      setError("");
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const commit = useMutation({
    mutationFn: () => post<any>(`/documents/${selectedId}/commit`),
    onSuccess: (result: any) => {
      setError("");
      setSuccess(`${result.labs.length} result${result.labs.length === 1 ? "" : "s"} written to the timeline with source ${result.document.id}.`);
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const generateInvestigation = useMutation({
    mutationFn: () => post<any>("/investigation-requests/generate"),
    onSuccess: () => {
      setError("");
      setSuccess("Investigation request drafted. Review the indication, allergy carry-forward and priority before approval.");
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const exportInvestigation = useMutation({
    mutationFn: (id: string) => post(`/investigation-requests/${id}/export`),
    onSuccess: () => {
      setSuccess("Request marked exported in the demo. No laboratory or radiology transmission occurred.");
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const generateRequest = useMutation({
    mutationFn: () => post<any>("/document-requests/generate"),
    onSuccess: () => {
      setError("");
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const exportRequest = useMutation({
    mutationFn: (id: string) => post(`/document-requests/${id}/export`),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const matchRequest = useMutation({
    mutationFn: ({ requestId, documentId }: { requestId: string; documentId: string }) =>
      post(`/document-requests/${requestId}/match`, { document_id: documentId }),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const latestRequest = drafts.data?.drafts?.[0];
  const confirmedDocs = documents.data?.documents.filter((item) => ["confirmed", "reviewed"].includes(item.ocr_status)) || [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Documents</h1>
          <div className="page-sub">
            One reading paper in, one structured requisition out. Low-confidence extractions stay amber until a human confirms them. The original image stays beside the parsed value.
          </div>
        </div>
        <div className="page-actions"><span className="badge badge-ai">OCR + requisition</span></div>
      </div>

      <div className="tabs">
        <button className={`tab ${tab === "inbound" ? "active" : ""}`} onClick={() => setParams({ tab: "inbound" })}>Inbound · F8</button>
        <button className={`tab ${tab === "requisition" ? "active" : ""}`} onClick={() => setParams({ tab: "requisition" })}>Requisition · F10</button>
        <button className={`tab ${tab === "followup" ? "active" : ""}`} onClick={() => setParams({ tab: "followup" })}>Follow-up (support)</button>
      </div>

      {error ? <div className="error-box mb-3">{error}</div> : null}
      {success ? <div className="success-box mb-3">{success}</div> : null}

      {tab === "inbound" ? (
        <div className="doc-layout">
          <div className="flex-col gap-3">
            <div className="card">
              <div className="card-head">
                <div><div className="card-title">Document queue</div><div className="card-sub">{documents.data?.documents.length || 0} documents</div></div>
                <label className="btn btn-primary btn-sm">
                  Upload scan
                  <input
                    type="file"
                    accept="image/*,application/pdf"
                    style={{ display: "none" }}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) upload.mutate(file);
                    }}
                  />
                </label>
              </div>
              {upload.isPending ? <div className="banner"><span className="spinner" /> Running extraction…</div> : null}
              <div className="list">
                {documents.data?.documents.map((item) => (
                  <button
                    key={item.id}
                    className="list-row"
                    style={{ background: item.id === selectedId ? "var(--accent-soft)" : undefined, border: 0, textAlign: "left", width: "100%" }}
                    onClick={() => { setSelectedId(item.id); setSuccess(""); setError(""); }}
                  >
                    <div style={{ flex: 1 }}>
                      <div className="fs-13" style={{ fontWeight: 600 }}>{item.filename}</div>
                      <div className="small muted">{new Date(item.uploaded_at).toLocaleString()} · {item.field_count} fields</div>
                    </div>
                    <span className={`badge ${item.ocr_status === "needs_confirmation" ? "badge-warning" : item.ocr_status === "confirmed" ? "badge-success" : "badge-neutral"}`}>
                      {item.ocr_status.replaceAll("_", " ")}
                    </span>
                  </button>
                ))}
                {!documents.data?.documents.length ? <div className="empty">No documents. Upload a synthetic scan to run OCR.</div> : null}
              </div>
            </div>

            {document.data ? (
              <div className="card">
                <div className="card-head">
                  <div><div className="card-title">Original scan</div><div className="card-sub">{document.data.filename}</div></div>
                  <span className="badge badge-neutral">{document.data.mime}</span>
                </div>
                <div className="scan-frame">
                  {document.data.mime === "application/pdf" ? (
                    <iframe src={document.data.image_url} title="Original PDF report" style={{ width: "100%", height: 520, border: 0 }} />
                  ) : (
                    <img src={document.data.image_url} alt="Scanned source document" />
                  )}
                </div>
                <div className="card-pad small muted" style={{ borderTop: "1px solid var(--border)" }}>
                  The original stays beside the extraction. Low-confidence fields cannot be committed until a human confirms them.
                </div>
              </div>
            ) : null}
          </div>

          <div className="flex-col gap-3">
            {document.data ? (
              <div className="card">
                <div className="card-head">
                  <div>
                    <div className="card-title">Extracted fields</div>
                    <div className="card-sub">Amber fields require confirmation before commit</div>
                  </div>
                  <span className={`badge ${document.data.ocr_status === "needs_confirmation" ? "badge-warning" : document.data.ocr_status === "confirmed" ? "badge-success" : "badge-neutral"}`}>
                    {document.data.ocr_status}
                  </span>
                </div>
                <div className="card-pad">
                  {document.data.extracted?.fields?.map((field, index) => (
                    <div className="field-row" key={`${field.name}-${index}`}>
                      <div className="flex items-center justify-between">
                        <div className="field-name">{field.name}</div>
                        <span className={`confidence ${field.confidence >= 0.8 ? "high" : "low"}`}>{Math.round(field.confidence * 100)}%</span>
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="field-value">{field.value} {field.unit}</span>
                        <span className="small muted">ref {field.reference_range || "—"}</span>
                      </div>
                      {field.confidence < 0.8 ? (
                        <div className="button-row mt-1">
                          <button className="btn btn-sm" onClick={() => confirmField.mutate({ index })} disabled={confirmField.isPending}>
                            Confirm value
                          </button>
                          <span className="small muted">Low confidence — click to confirm the parsed text.</span>
                        </div>
                      ) : null}
                    </div>
                  ))}
                  <div className="button-row mt-3">
                    <button className="btn btn-primary" onClick={() => commit.mutate()} disabled={commit.isPending || document.data.ocr_status === "confirmed"}>
                      {commit.isPending ? <><span className="spinner" /> Committing…</> : "Commit results to timeline"}
                    </button>
                    <span className="small muted">Writes one sourced lab event per confirmed field.</span>
                  </div>
                  {document.data.ocr_status === "confirmed" ? (
                    <div className="banner success mt-2">Confirmed. The parsed values are on the timeline with this document as their source.</div>
                  ) : null}
                </div>
              </div>
            ) : (
              <div className="card empty"><div className="empty-title">Select a document.</div><div>The scan and its extraction will appear side by side.</div></div>
            )}

            <div className="card">
              <div className="card-head"><div className="card-title">What OCR does not decide</div></div>
              <div className="card-pad small muted" style={{ lineHeight: 1.7 }}>
                The model extracts text and a confidence. It does not write the value to the record. A human confirms low-confidence fields and commits; only then does the lab event exist.
              </div>
            </div>
          </div>
        </div>
      ) : tab === "requisition" ? (
        <div className="flex-col gap-3">
          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">Investigation and radiology requisitions</div>
                <div className="card-sub">Pre-filled from the documented record. Allergies are carried forward and must be verified before use.</div>
              </div>
              <button className="btn btn-primary btn-sm" onClick={() => generateInvestigation.mutate()} disabled={generateInvestigation.isPending}>
                {generateInvestigation.isPending ? <><span className="spinner" /> Drafting…</> : "Draft requisition"}
              </button>
            </div>
            <table className="table">
              <thead><tr><th>Study</th><th>Priority</th><th>Allergy flag</th><th>Status</th><th className="right">Action</th></tr></thead>
              <tbody>
                {investigations.data?.requests.map((request) => (
                  <tr key={request.id}>
                    <td>
                      <div style={{ fontWeight: 550 }}>{request.study}</div>
                      <div className="small muted">{request.request_type} · {request.indication}</div>
                    </td>
                    <td><span className={`badge ${request.priority === "routine" ? "badge-neutral" : "badge-warning"}`}>{request.priority}</span></td>
                    <td className="small">
                      {request.allergies_to_verify?.length
                        ? request.allergies_to_verify.map((item) => `${item.substance}${item.verified ? " ✓" : " (verify)"}`).join(", ")
                        : "No documented allergy"}
                    </td>
                    <td><span className={`badge ${request.status === "exported" ? "badge-success" : "badge-neutral"}`}>{request.status}</span></td>
                    <td className="right">
                      {request.status !== "exported" ? (
                        <button className="btn btn-sm" onClick={() => exportInvestigation.mutate(request.id)} disabled={exportInvestigation.isPending}>
                          Mark exported
                        </button>
                      ) : <span className="small muted">Demo export complete</span>}
                    </td>
                  </tr>
                ))}
                {!investigations.data?.requests.length ? <tr><td colSpan={5}><div className="empty">No investigation requests yet.</div></td></tr> : null}
              </tbody>
            </table>
            <div className="card-pad" style={{ borderTop: "1px solid var(--border)" }}>
              <div className="banner warning">Review-only workflow. No laboratory, radiology, fax or external transmission exists in this build.</div>
            </div>
          </div>

          {latestRequest ? <DraftReview draft={latestRequest} /> : (
            <div className="card empty"><div className="empty-title">No requisition draft.</div><div>Draft a requisition from the documented diagnosis, allergies and recent results.</div></div>
          )}
        </div>
      ) : (
        <div className="flex-col gap-3">
          <div className="card">
            <div className="card-head">
              <div><div className="card-title">Missing-records and pre-authorization follow-up</div><div className="card-sub">Supporting workflow, kept separate from F10</div></div>
              <button className="btn btn-primary btn-sm" onClick={() => generateRequest.mutate()} disabled={generateRequest.isPending}>
                {generateRequest.isPending ? <><span className="spinner" /> Drafting…</> : "Create follow-up request"}
              </button>
            </div>
            <table className="table">
              <thead><tr><th>Request</th><th>Recipient</th><th>Due</th><th>Status</th><th className="right">Actions</th></tr></thead>
              <tbody>
                {requests.data?.requests.map((request) => (
                  <tr key={request.id}>
                    <td>
                      <div style={{ fontWeight: 550 }}>{request.records_requested.join(", ")}</div>
                      <div className="small muted">{request.request_type.replaceAll("_", " ")}</div>
                    </td>
                    <td className="small">{request.recipient}</td>
                    <td className="mono small">{request.due_at ? new Date(request.due_at).toLocaleDateString() : "—"}</td>
                    <td><span className={`badge ${request.status === "overdue" ? "badge-warning" : request.status === "matched" ? "badge-success" : "badge-neutral"}`}>{request.status}</span></td>
                    <td className="right">
                      <div className="button-row" style={{ justifyContent: "flex-end" }}>
                        {["approved", "overdue"].includes(request.status) ? (
                          <button className="btn btn-sm" onClick={() => exportRequest.mutate(request.id)}>Mark exported</button>
                        ) : null}
                        {request.status !== "matched" ? (
                          <>
                            <select
                              className="select"
                              style={{ width: 150, padding: "3px 6px", fontSize: 11 }}
                              value={matchChoice[request.id] || ""}
                              onChange={(event) => setMatchChoice((current) => ({ ...current, [request.id]: event.target.value }))}
                            >
                              <option value="">Match a document…</option>
                              {confirmedDocs.map((item) => <option key={item.id} value={item.id}>{item.filename}</option>)}
                            </select>
                            <button
                              className="btn btn-sm"
                              disabled={!matchChoice[request.id]}
                              onClick={() => matchRequest.mutate({ requestId: request.id, documentId: matchChoice[request.id] })}
                            >
                              Match
                            </button>
                          </>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
                {!requests.data?.requests.length ? <tr><td colSpan={5}><div className="empty">No outbound requests yet.</div></td></tr> : null}
              </tbody>
            </table>
            <div className="card-pad" style={{ borderTop: "1px solid var(--border)" }}>
              <div className="banner warning">Demo export only. There is no fax, email or payer transmission in this build.</div>
            </div>
          </div>

          <div className="card empty">
            <div className="empty-title">Supporting workflow, not a PRD module</div>
            <div>Missing-record and pre-authorization follow-up stays available for revenue operations. F10 is the investigation and radiology requisition workflow.</div>
          </div>
        </div>
      )}
    </>
  );
}
