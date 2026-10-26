import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { get, post } from "../api";
import type { DocumentRequest, DocumentSummary, Draft, InvestigationRequest } from "../types";
import { DraftReview } from "../components/DraftReview";
import { useCan } from "../session";
import { DocTypeSelect } from "../features/f08/DocTypeSelect";
import { ManualEntryForm } from "../features/f08/ManualEntryForm";
import { uploadReport } from "../features/f08/upload";
import {
  AUTO_ACTOR,
  commitSummary,
  docTypeLabel,
  type CommitResult,
  type DocType,
  type F08Document,
  type UploadResult,
} from "../features/f08/types";
import { PageHeader } from "../components/PageHeader";
import { Icon } from "../components/icons";
import {
  Banner,
  DataTable,
  Disclosure,
  EmptyState,
  ListRow,
  MetaChip,
  Panel,
  Pill,
  Progress,
  Skeleton,
  Tabs,
  Toolbar,
  type Tone,
} from "../components/ui";

const DOC_ICON: Record<string, string> = {
  lab_report: "lab",
  prescription: "pill",
  radiology_report: "scan",
  discharge_summary: "discharge",
};

/** Same status colours as before: amber needs a person, green is saved, the rest neutral. */
function statusTone(status: string): Tone {
  return status === "needs_confirmation" ? "warning" : status === "confirmed" ? "success" : "neutral";
}

export function DocumentsPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "inbound";
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [matchChoice, setMatchChoice] = useState<Record<string, string>>({});
  const [docType, setDocType] = useState<DocType>("lab_report");
  const canUpload = useCan("upload_document");
  const canConfirm = useCan("confirm_document");

  const documents = useQuery<{ documents: DocumentSummary[] }>({
    queryKey: ["documents"],
    queryFn: () => get("/documents"),
  });
  const document = useQuery<F08Document>({
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
    mutationFn: (file: File) => uploadReport(file, docType),
    onSuccess: (result: UploadResult) => {
      setSelectedId(result.id);
      setError("");
      if (result.auto_committed) {
        const alerts = result.new_alerts.map((alert) => alert.title);
        setSuccess(
          `Saved to the timeline automatically: ${commitSummary(result.doc_type, result.events.length)}. ` +
            "The values are marked unreviewed; a doctor must review them." +
            (alerts.length ? ` New alerts: ${alerts.join("; ")}.` : ""),
        );
      } else if (result.auto_commit_error) {
        setSuccess(
          `Upload complete, but the automatic save did not finish (${result.auto_commit_error}). ` +
            "Check the values against the original and use Save to timeline.",
        );
      } else {
        setSuccess(
          result.ocr_status === "needs_manual_entry"
            ? "Upload complete. No text could be read from this file. Type the values from the original."
            : "Upload complete. Check the values against the original before saving.",
        );
      }
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
    mutationFn: () => post<CommitResult>(`/documents/${selectedId}/commit`),
    onSuccess: (result) => {
      setError("");
      setSuccess(`${commitSummary(result.document.doc_type, result.events.length)}, with source ${result.document.id}.`);
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
  const loadedFields = document.data?.extracted?.fields || [];
  const confidentCount = loadedFields.filter((field) => field.confidence >= 0.8).length;
  const tabItems = [
    { key: "inbound", label: "Inbound reports" },
    { key: "requisition", label: "Investigation requests" },
    { key: "followup", label: "Records follow-up" },
  ];

  return (
    <div className="pg-documents">
      <PageHeader
        title={tab === "requisition" ? "Investigation requests" : tab === "followup" ? "Records follow-up" : "Inbound reports"}
        description={tab === "requisition"
          ? "Imaging and laboratory requests pre-filled from the record. Allergies must be checked before a request is approved."
          : tab === "followup"
            ? "Requests for missing outside records and pre-authorisation, and matching what arrives."
            : "Outside reports are read automatically. The original stays beside each value, and uncertain values must be confirmed by a person."}
      />

      <Tabs label="Documents" items={tabItems} value={tab} onSelect={(key) => setParams({ tab: key })} />

      {error ? <Banner tone="danger" role="alert">{error}</Banner> : null}
      {success ? <Banner tone="success" role="status">{success}</Banner> : null}

      {tab === "inbound" ? (
        <div className="inbox">
          <Panel
            className="doc-queue"
            title="Document queue"
            count={documents.data?.documents.length || 0}
            sub="Choose a report to check it against the original."
          >
            <Toolbar label="Upload a report">
              <DocTypeSelect value={docType} onChange={setDocType} />
              <span className="toolbar-spacer" />
              <label
                className="btn btn-primary btn-sm doc-upload"
                style={canUpload ? undefined : { opacity: 0.5, pointerEvents: "none" }}
                title={canUpload ? undefined : "Your role cannot upload documents."}
                aria-busy={upload.isPending || undefined}
              >
                {upload.isPending ? <span className="spinner" /> : <Icon name="upload" size={15} />}
                Upload report
                <input
                  type="file"
                  accept="image/*,application/pdf"
                  className="sr-only"
                  disabled={!canUpload}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) upload.mutate(file);
                    event.target.value = "";
                  }}
                />
              </label>
            </Toolbar>
            <div className="doc-queue-body">
              {upload.isPending ? (
                <>
                  <div className="doc-reading" role="status"><span className="spinner" /> Running extraction…</div>
                  <Skeleton variant="rows" count={1} />
                </>
              ) : null}
              {documents.isLoading ? (
                <Skeleton variant="rows" count={4} />
              ) : documents.data?.documents.length ? (
                <div className="rows">
                  {documents.data.documents.map((item) => (
                    <ListRow
                      key={item.id}
                      icon={DOC_ICON[item.doc_type] || "scan"}
                      tone={item.ocr_status === "needs_confirmation" ? "warning" : item.ocr_status === "confirmed" ? "success" : undefined}
                      selected={item.id === selectedId}
                      title={item.filename}
                      meta={<>{docTypeLabel(item.doc_type)} · {new Date(item.uploaded_at).toLocaleString()}</>}
                      chips={
                        <>
                          <Pill tone={statusTone(item.ocr_status)} dot>{item.ocr_status.replaceAll("_", " ")}</Pill>
                          {typeof item.field_count === "number" ? <MetaChip>{item.field_count} field{item.field_count === 1 ? "" : "s"}</MetaChip> : null}
                        </>
                      }
                      onClick={() => { setSelectedId(item.id); setSuccess(""); setError(""); }}
                    />
                  ))}
                </div>
              ) : (
                <EmptyState icon="upload" title="No documents yet">
                  Choose the report type, then Upload report. The reader fills in the values and keeps the original beside them.
                </EmptyState>
              )}
            </div>
          </Panel>

          {document.data ? (
            <Panel
              className="doc-scan"
              title="Original scan"
              sub={document.data.filename}
              actions={<Pill>{docTypeLabel(document.data.doc_type)} · {document.data.mime}</Pill>}
              footer="The original stays beside the extraction. Low-confidence fields cannot be committed until a human confirms them."
              padded
            >
              <div className="scan-frame">
                {document.data.mime === "application/pdf" ? (
                  <iframe src={document.data.image_url} title="Original PDF report" className="doc-pdf" />
                ) : (
                  <img src={document.data.image_url} alt="Scanned source document" />
                )}
              </div>
            </Panel>
          ) : selectedId && document.isLoading ? (
            <Panel title="Original scan">
              <Skeleton count={8} />
            </Panel>
          ) : (
            <Panel>
              <EmptyState icon="scan" title="Select a document">
                The scan and its extraction will appear side by side. Pick a report from the queue, or upload one.
              </EmptyState>
            </Panel>
          )}

          <div className="rail">
            {document.data ? (
              <Panel
                className="doc-fields"
                title="Extracted fields"
                sub="Amber values are below 80% confidence and need a person to confirm them before saving."
                actions={<Pill tone={statusTone(document.data.ocr_status)} dot>{document.data.ocr_status.replaceAll("_", " ")}</Pill>}
              >
                <div className="panel-body doc-fields-body">
                  {loadedFields.length ? (
                    <Progress
                      value={confidentCount}
                      max={loadedFields.length}
                      label={`${confidentCount} of ${loadedFields.length} values confident`}
                      tone={confidentCount === loadedFields.length ? "success" : "warning"}
                    />
                  ) : null}
                  {document.data.ocr_status === "needs_manual_entry" ? (
                    <Banner tone="warning">
                      No text could be read from this file. Nothing was filled in. Read the original beside this panel and type the values below.
                    </Banner>
                  ) : null}
                  <div className="doc-field-list">
                    {document.data.extracted?.fields?.map((field, index) => (
                      <div className="field-row" key={`${field.name}-${index}`}>
                        <div className="doc-field-head">
                          <div className="field-name">{field.name}</div>
                          <span className={`confidence ${field.confidence >= 0.8 ? "high" : "low"}`}>{Math.round(field.confidence * 100)}%</span>
                        </div>
                        <div className="doc-field-value">
                          <span className="field-value">{field.value} {field.unit}</span>
                          {document.data.doc_type === "lab_report" ? (
                            <span className="small muted">ref {field.reference_range || "not read"}</span>
                          ) : document.data.doc_type === "prescription" ? (
                            <span className="small muted">{field.reference_range || "no frequency read"}</span>
                          ) : null}
                          {field.manual ? <Pill>typed by hand</Pill> : null}
                        </div>
                        {field.confidence < 0.8 ? (
                          <div className="doc-field-confirm">
                            <button className="btn btn-sm" onClick={() => confirmField.mutate({ index })} disabled={confirmField.isPending || !canConfirm}>
                              <Icon name="check" size={14} />
                              Confirm value
                            </button>
                            <span className="small muted">Low confidence. Check the original, then confirm the parsed text.</span>
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                  {document.data.ocr_status !== "confirmed" ? (
                    document.data.ocr_status === "needs_manual_entry" ? (
                      <ManualEntryForm
                        documentId={document.data.id}
                        docType={document.data.doc_type}
                        allowed={canConfirm}
                        onError={setError}
                      />
                    ) : (
                      <Disclosure title="Add a value the reader missed">
                        <ManualEntryForm
                          documentId={document.data.id}
                          docType={document.data.doc_type}
                          allowed={canConfirm}
                          onError={setError}
                        />
                      </Disclosure>
                    )
                  ) : null}
                  {document.data.ocr_status === "confirmed" ? (
                    <Banner tone="success">
                      {document.data.confirmed_by === AUTO_ACTOR
                        ? "Saved automatically (clean lab report). The values are on the timeline with this document as their source and stay unreviewed until a doctor reviews them."
                        : "Saved. The values are on the timeline with this document as their source."}
                    </Banner>
                  ) : null}
                </div>
                <div className="sticky-foot">
                  <span className="small muted doc-save-hint">
                    {document.data.doc_type === "prescription"
                      ? "Adds each confirmed medicine to the home medicines."
                      : document.data.doc_type === "radiology_report" || document.data.doc_type === "discharge_summary"
                        ? "Adds one review note holding the confirmed lines."
                        : "Adds one sourced result per confirmed field."}
                  </span>
                  <button
                    className="btn btn-primary"
                    onClick={() => commit.mutate()}
                    aria-busy={commit.isPending || undefined}
                    disabled={
                      commit.isPending ||
                      !canConfirm ||
                      document.data.ocr_status === "confirmed" ||
                      !document.data.extracted?.fields?.length
                    }
                  >
                    {commit.isPending ? <><span className="spinner" /> Saving…</> : "Save to timeline"}
                  </button>
                </div>
              </Panel>
            ) : selectedId && document.isLoading ? (
              <Panel title="Extracted fields">
                <Skeleton count={6} />
              </Panel>
            ) : null}

            <Disclosure title="What OCR does not decide">
              The reader copies text from the file and gives a confidence. It does not write to the record, with one exception: a clean lab report (every value read at 80% confidence or more) is saved on upload as unreviewed results, and a doctor still reviews them. For every other report, a person confirms uncertain values and saves; only then does anything reach the timeline. If no text can be read, nothing is filled in and you type the values.
            </Disclosure>
          </div>
        </div>
      ) : tab === "requisition" ? (
        <>
          <Panel
            title="Investigation and radiology requisitions"
            sub="Pre-filled from the documented record. Allergies are carried forward and must be verified before use."
          >
            <Toolbar label="Requisition actions">
              <span className="small muted">{investigations.data?.requests.length || 0} requests</span>
              <span className="toolbar-spacer" />
              <button
                className="btn btn-primary btn-sm"
                onClick={() => generateInvestigation.mutate()}
                disabled={generateInvestigation.isPending}
                aria-busy={generateInvestigation.isPending || undefined}
              >
                {generateInvestigation.isPending ? <><span className="spinner" /> Drafting…</> : <><Icon name="plus" size={15} /> Draft requisition</>}
              </button>
            </Toolbar>
            <DataTable<InvestigationRequest>
              caption="Investigation requests"
              rows={investigations.data?.requests || []}
              rowKey={(request) => request.id}
              loading={investigations.isLoading}
              empty={
                <EmptyState icon="request" title="No investigation requests yet">
                  Draft requisition pre-fills a request from the documented diagnosis, allergies and recent results.
                </EmptyState>
              }
              columns={[
                {
                  key: "study",
                  header: "Study",
                  sort: (request) => request.study,
                  cell: (request) => (
                    <>
                      <div className="cell-strong">{request.study}</div>
                      <div className="cell-sub">{request.request_type} · {request.indication}</div>
                    </>
                  ),
                },
                {
                  key: "priority",
                  header: "Priority",
                  sort: (request) => request.priority,
                  cell: (request) => <Pill tone={request.priority === "routine" ? "neutral" : "warning"}>{request.priority}</Pill>,
                },
                {
                  key: "allergy",
                  header: "Allergy flag",
                  cell: (request) =>
                    request.allergies_to_verify?.length ? (
                      <span className="pill-row">
                        {request.allergies_to_verify.map((item) => (
                          <Pill key={item.substance} tone={item.verified ? "success" : "warning"} icon={item.verified ? "check" : "alert"}>
                            {item.substance}{item.verified ? "" : " (verify)"}
                          </Pill>
                        ))}
                      </span>
                    ) : (
                      <span className="small muted">No documented allergy</span>
                    ),
                },
                {
                  key: "status",
                  header: "Status",
                  sort: (request) => request.status,
                  cell: (request) => <Pill tone={request.status === "exported" ? "success" : "neutral"} dot>{request.status}</Pill>,
                },
                {
                  key: "action",
                  header: "Action",
                  align: "right",
                  cell: (request) =>
                    request.status !== "exported" ? (
                      <button className="btn btn-sm" onClick={() => exportInvestigation.mutate(request.id)} disabled={exportInvestigation.isPending}>
                        Mark exported
                      </button>
                    ) : <span className="small muted">Demo export complete</span>,
                },
              ]}
            />
            <div className="panel-body">
              <Banner tone="warning">Review-only workflow. No laboratory, radiology, fax or external transmission exists in this build.</Banner>
            </div>
          </Panel>

          {latestRequest ? <DraftReview draft={latestRequest} /> : (
            <Panel>
              <EmptyState icon="request" title="No requisition draft yet">
                Draft a requisition from the documented diagnosis, allergies and recent results. It appears here for review before approval.
              </EmptyState>
            </Panel>
          )}
        </>
      ) : (
        <>
          <Panel title="Missing-records and pre-authorization follow-up" sub="Separate from the discharge summary">
            <Toolbar label="Follow-up actions">
              <span className="small muted">{requests.data?.requests.length || 0} requests</span>
              <span className="toolbar-spacer" />
              <button
                className="btn btn-primary btn-sm"
                onClick={() => generateRequest.mutate()}
                disabled={generateRequest.isPending}
                aria-busy={generateRequest.isPending || undefined}
              >
                {generateRequest.isPending ? <><span className="spinner" /> Drafting…</> : <><Icon name="plus" size={15} /> Create follow-up request</>}
              </button>
            </Toolbar>
            <DataTable<DocumentRequest>
              caption="Records follow-up requests"
              rows={requests.data?.requests || []}
              rowKey={(request) => request.id}
              loading={requests.isLoading}
              empty={
                <EmptyState icon="folder" title="No outbound requests yet">
                  Create follow-up request drafts a request for records that are missing from the chart. Match the report here when it arrives.
                </EmptyState>
              }
              columns={[
                {
                  key: "request",
                  header: "Request",
                  cell: (request) => (
                    <>
                      <div className="cell-strong">{request.records_requested.join(", ")}</div>
                      <div className="cell-sub">{request.request_type.replaceAll("_", " ")}</div>
                    </>
                  ),
                },
                { key: "recipient", header: "Recipient", sort: (request) => request.recipient, cell: (request) => request.recipient },
                {
                  key: "due",
                  header: "Due",
                  sort: (request) => request.due_at || null,
                  cell: (request) => (
                    <span className="mono small">{request.due_at ? new Date(request.due_at).toLocaleDateString() : "not set"}</span>
                  ),
                },
                {
                  key: "status",
                  header: "Status",
                  sort: (request) => request.status,
                  cell: (request) => (
                    <Pill tone={request.status === "overdue" ? "warning" : request.status === "matched" ? "success" : "neutral"} dot>
                      {request.status}
                    </Pill>
                  ),
                },
                {
                  key: "actions",
                  header: "Actions",
                  align: "right",
                  cell: (request) => (
                    <div className="doc-row-actions">
                      {["approved", "overdue"].includes(request.status) ? (
                        <button className="btn btn-sm" onClick={() => exportRequest.mutate(request.id)}>Mark exported</button>
                      ) : null}
                      {request.status !== "matched" ? (
                        <>
                          <select
                            className="select select-sm doc-match-select"
                            aria-label={`Document to match with ${request.records_requested.join(", ")}`}
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
                  ),
                },
              ]}
            />
            <div className="panel-body">
              <Banner tone="warning">Demo export only. There is no fax, email or payer transmission in this build.</Banner>
            </div>
          </Panel>

          <Banner title="Supporting workflow">
            Missing-record and pre-authorization follow-up stays available for revenue operations. F10 is the investigation and radiology requisition workflow.
          </Banner>
        </>
      )}
    </div>
  );
}
