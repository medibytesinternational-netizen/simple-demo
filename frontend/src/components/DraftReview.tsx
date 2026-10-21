import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post } from "../api";
import type { Claim, Draft, Meta } from "../types";
import { EvidenceChip } from "./Evidence";
import { Modal } from "./Modal";

const FEATURE_LABELS: Record<string, string> = {
  F1: "Consultation note",
  F2: "Admission assessment",
  F3: "Round handover",
  F4: "Daily progress note",
  F6: "Medication reconciliation",
  F7: "ICU flow sheet",
  F9: "Discharge summary",
  F10: "Investigation and radiology request",
  F11: "Smart referral",
  F12: "Claim pack review",
  F13: "Revenue leakage review",
};

export function DraftReview({ draft }: { draft: Draft }) {
  const queryClient = useQueryClient();
  const [editMode, setEditMode] = useState(false);
  const [editText, setEditText] = useState(() => JSON.stringify(draft.content, null, 2));
  const [rejectOpen, setRejectOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [selectedTasks, setSelectedTasks] = useState<number[]>([]);
  const [f4Exam, setF4Exam] = useState("");
  const [f4Plan, setF4Plan] = useState("");

  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => fetch("/api/meta").then((r) => r.json()) });
  const tasks = useMemo<any[]>(() => draft.content?.proposed_tasks || [], [draft.content]);
  useEffect(() => {
    const defaults = tasks
      .map((task: any, index: number) => ({ task, index }))
      .filter(({ task }: any) => !String(task.title || "").toLowerCase().includes("ibuprofen") && Number(task.confidence ?? 1) >= 0.7)
      .map(({ index }: any) => index);
    setSelectedTasks(defaults);
    setEditText(JSON.stringify(draft.content, null, 2));
    setEditMode(false);
    setF4Exam(draft.content?.exam?.general?.text || "");
    setF4Plan(draft.content?.plan?.text || "");
  }, [draft.id, draft.content, tasks]);

  const invalidate = () => queryClient.invalidateQueries();

  const approve = useMutation({
    mutationFn: async () => {
      let content: any = undefined;
      if (editMode) content = JSON.parse(editText);
      return post<any>(`/drafts/${draft.id}/approve`, {
        content,
        approved_by: meta.data?.demo_user || "Dr. Meera Shah",
      });
    },
    onSuccess: () => {
      setError("");
      invalidate();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const reject = useMutation({
    mutationFn: () => post<any>(`/drafts/${draft.id}/reject`, { reason, actor: meta.data?.demo_user }),
    onSuccess: () => {
      setRejectOpen(false);
      setReason("");
      setError("");
      invalidate();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const saveEdit = useMutation({
    mutationFn: async () => {
      const parsed = JSON.parse(editText);
      return patch<any>(`/drafts/${draft.id}`, { content: parsed, editor: meta.data?.demo_user });
    },
    onSuccess: () => {
      setEditMode(false);
      setError("");
      invalidate();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const saveF4 = useMutation({
    mutationFn: async () => {
      const content = JSON.parse(JSON.stringify(draft.content || {}));
      content.exam = content.exam || {};
      content.exam.general = {
        text: f4Exam.trim(),
        source_event_ids: [],
        source_segment_ids: [],
        confidence: 1,
        human_authored: true,
      };
      content.plan = {
        text: f4Plan.trim(),
        source_event_ids: [],
        source_segment_ids: [],
        confidence: 1,
        human_authored: true,
      };
      content.not_documented = (content.not_documented || []).filter(
        (item: unknown) => !/exam|plan/i.test(String(item)),
      );
      return patch<any>(`/drafts/${draft.id}`, { content, editor: meta.data?.demo_user });
    },
    onSuccess: () => {
      setError("");
      invalidate();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const accept = useMutation({
    mutationFn: () => post<any>(`/drafts/${draft.id}/accept-tasks`, { indices: selectedTasks, actor: meta.data?.demo_user }),
    onSuccess: () => {
      setError("");
      invalidate();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const verifyAllergy = useMutation({
    mutationFn: (substance: string) =>
      post<any>(`/drafts/${draft.id}/verify-allergy`, {
        substance,
        actor: meta.data?.demo_user,
      }),
    onSuccess: () => {
      setError("");
      invalidate();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const consents = useQuery<{ consents: Array<{ id: string; consent_type: string; granted: boolean; occurred_at: string }> }>({
    queryKey: ["consents", draft.patient_id, draft.encounter_id],
    queryFn: () => get(`/patients/${draft.patient_id}/consents?encounter_id=${draft.encounter_id || ""}`),
    enabled: draft.feature === "F1",
  });

  const recordConsent = useMutation({
    mutationFn: () =>
      post<any>(`/patients/${draft.patient_id}/consents?encounter_id=${draft.encounter_id || ""}`, {
        consent_type: "consultation_capture",
        granted: true,
        actor: meta.data?.demo_user,
        note: "Patient agrees to consultation capture for this episode.",
      }),
    onSuccess: () => {
      setError("");
      invalidate();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const isApproved = draft.status === "approved";
  const isRejected = draft.status === "rejected";
  const f4Incomplete =
    draft.feature === "F4" &&
    (!draft.content?.exam?.general?.text || !draft.content?.plan?.text);
  const f2Unverified =
    draft.feature === "F2" &&
    (draft.content?.allergies_to_verify || []).some((item: any) => !item.verified);
  const f1NoConsent =
    draft.feature === "F1" &&
    !consents.data?.consents?.some((entry) => entry.granted);
  const approvalBlocked = f4Incomplete || f2Unverified || f1NoConsent;
  const actionLabel =
    draft.feature === "F9"
      ? "Sign & lock"
      : draft.feature === "F10"
        ? "Approve request"
        : draft.feature === "F11"
          ? "Approve & queue referral (demo)"
          : "Approve & sign";

  return (
    <div className={`draft-shell ${isApproved ? "draft-approved" : ""} ${isRejected ? "draft-rejected" : ""}`}>
      <div className="draft-head">
        <div>
          <div className="draft-title">{FEATURE_LABELS[draft.feature] || draft.feature}</div>
          <div className="draft-meta">
            <span className={`badge ${isApproved ? "badge-success" : isRejected ? "badge-critical" : "badge-ai"}`}>
              {isApproved ? "Approved" : isRejected ? "Rejected" : draft.status === "human_edited" ? "Human edited" : "AI draft"}
            </span>
            <span>{draft.model}</span>
            <span>prompt {draft.prompt_version}</span>
            <span>{draft.evidence_event_ids.length} source{draft.evidence_event_ids.length === 1 ? "" : "s"}</span>
            {draft.edited_by ? <span>edited by {draft.edited_by}</span> : null}
          </div>
        </div>
        {!isApproved && !isRejected ? (
          <button className="btn btn-sm" onClick={() => setEditMode((value) => !value)}>
            {editMode ? "Stop editing" : draft.feature === "F4" ? "Edit full JSON" : "Edit JSON"}
          </button>
        ) : null}
      </div>

      <div className="draft-body">
        {error ? <div className="error-box mb-3">{error}</div> : null}
        {isApproved ? (
          <div className="banner success mb-3">
            Committed to the timeline by {draft.approved_by || "clinician"}
            {draft.committed_event_id ? <span className="mono"> · {draft.committed_event_id}</span> : null}
          </div>
        ) : null}
        {isRejected ? (
          <div className="banner danger mb-3">Rejected: {draft.rejected_reason}</div>
        ) : null}

        {draft.feature === "F1" ? (
          <div className={`banner ${f1NoConsent ? "warning" : "success"} mb-3`}>
            {f1NoConsent ? (
              <div className="flex items-center justify-between gap-2">
                <span>Consent for consultation capture has not been recorded. The model cannot record it for you.</span>
                <button className="btn btn-sm" onClick={() => recordConsent.mutate()} disabled={recordConsent.isPending}>
                  {recordConsent.isPending ? "Recording…" : "Record consent"}
                </button>
              </div>
            ) : (
              <span>Consent for consultation capture is recorded and audited.</span>
            )}
          </div>
        ) : null}

        {draft.feature === "F2" && draft.content?.allergies_to_verify?.length ? (
          <div className="mb-3">
            <div className="section-label">Allergy verification — explicit clinician action</div>
            <table className="table">
              <thead><tr><th>Substance</th><th>Reaction</th><th>Status</th><th>Source</th><th /></tr></thead>
              <tbody>
                {draft.content.allergies_to_verify.map((item: any, index: number) => (
                  <tr key={`${item.substance}-${index}`}>
                    <td>{item.substance}</td>
                    <td>{item.reaction || "—"}</td>
                    <td>
                      <span className={`badge ${item.verified ? "badge-success" : "badge-warning"}`}>
                        {item.verified ? "verified" : "unverified"}
                      </span>
                    </td>
                    <td><EvidenceChip eventIds={item.source_event_id ? [item.source_event_id] : []} /></td>
                    <td className="right">
                      {!item.verified && !isApproved && !isRejected ? (
                        <button className="btn btn-sm" onClick={() => verifyAllergy.mutate(item.substance)} disabled={verifyAllergy.isPending}>
                          Verify
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {draft.feature === "F4" && !editMode && !isApproved && !isRejected ? (
          <div className="card mb-3" style={{ padding: 14 }}>
            <div className="section-label">Document required sections — clinician-authored</div>
            <div className="small muted mb-2">
              The draft will not invent examination findings or a plan. What you type is attributed to you,
              not to the transcript.
            </div>
            <label className="field-label" htmlFor={`f4-exam-${draft.id}`}>Examination</label>
            <textarea
              id={`f4-exam-${draft.id}`}
              className="textarea small mb-2"
              placeholder="e.g. Right lower leg erythema reduced; chest clear; no pedal oedema."
              value={f4Exam}
              onChange={(event) => setF4Exam(event.target.value)}
            />
            <label className="field-label" htmlFor={`f4-plan-${draft.id}`}>Plan</label>
            <textarea
              id={`f4-plan-${draft.id}`}
              className="textarea small"
              placeholder="e.g. Continue IV flucloxacillin; hold metformin; repeat renal panel tomorrow."
              value={f4Plan}
              onChange={(event) => setF4Plan(event.target.value)}
            />
            <div className="button-row mt-2">
              <button
                className="btn btn-primary btn-sm"
                onClick={() => saveF4.mutate()}
                disabled={!f4Exam.trim() || !f4Plan.trim() || saveF4.isPending}
              >
                {saveF4.isPending ? "Saving…" : "Save clinician documentation"}
              </button>
              {saveF4.isSuccess ? <span className="small muted">Saved as human-authored and audited.</span> : null}
            </div>
          </div>
        ) : null}

        {editMode ? (
          <div className="draft-editing">
            <div className="small muted mb-2">
              Edit the validated JSON. Saving re-validates the draft and marks it human-edited.
            </div>
            <textarea className="textarea" value={editText} onChange={(event) => setEditText(event.target.value)} />
            <div className="button-row mt-2">
              <button className="btn btn-primary btn-sm" onClick={() => saveEdit.mutate()} disabled={saveEdit.isPending}>
                {saveEdit.isPending ? "Saving…" : "Save edits"}
              </button>
            </div>
          </div>
        ) : (
          <DraftContent draft={draft} selectedTasks={selectedTasks} setSelectedTasks={setSelectedTasks} />
        )}

        {draft.feature === "F3" && tasks.length ? (
          <div className="mt-4">
            <div className="section-label">Proposed tasks — choose what becomes real</div>
            <div className="list card">
              {tasks.map((task, index) => (
                <label className="list-row" key={`${task.title}-${index}`} style={{ cursor: "pointer" }}>
                  <input
                    className="checkbox"
                    type="checkbox"
                    checked={selectedTasks.includes(index)}
                    onChange={(event) => {
                      setSelectedTasks((current) =>
                        event.target.checked ? [...current, index] : current.filter((item) => item !== index),
                      );
                    }}
                  />
                  <span style={{ flex: 1 }}>
                    <span className="fs-13" style={{ fontWeight: 600 }}>{task.title}</span>
                    <span className="small muted" style={{ display: "block" }}>
                      {task.priority} · due in {task.due_in_hours}h · {Math.round((task.confidence ?? 1) * 100)}% confidence
                    </span>
                  </span>
                  <EvidenceChip eventIds={[]} segmentIds={task.source_segment_ids} />
                </label>
              ))}
            </div>
            <div className="button-row mt-2">
              <button
                className="btn btn-primary btn-sm"
                disabled={!isApproved || accept.isPending || !selectedTasks.length}
                onClick={() => accept.mutate()}
              >
                {accept.isPending ? "Accepting…" : `Accept ${selectedTasks.length} selected task${selectedTasks.length === 1 ? "" : "s"}`}
              </button>
              {!isApproved ? <span className="small muted">Approve the note first, then accept tasks.</span> : null}
            </div>
            {accept.isSuccess ? <div className="success-box mt-2">Tasks accepted. They are now real work items.</div> : null}
          </div>
        ) : null}
      </div>

      {!isApproved && !isRejected ? (
        <div className="draft-actions">
          <div>
            {f4Incomplete ? (
              <div className="small" style={{ color: "var(--warning)", fontWeight: 600 }}>
                Examination and plan are required. Document them in the clinician-authored editor before signing.
              </div>
            ) : f2Unverified ? (
              <div className="small" style={{ color: "var(--warning)", fontWeight: 600 }}>
                Verify the documented allergy below. A model may not mark an allergy as verified.
              </div>
            ) : f1NoConsent ? (
              <div className="small" style={{ color: "var(--warning)", fontWeight: 600 }}>
                Record the patient's consent for consultation capture before signing.
              </div>
            ) : (
              <div className="small muted">Nothing is written until you approve. Every commit is audited.</div>
            )}
          </div>
          <div className="button-row">
            <button className="btn btn-danger btn-sm" onClick={() => setRejectOpen(true)}>
              Reject
            </button>
            <button className="btn btn-primary" onClick={() => approve.mutate()} disabled={approve.isPending || approvalBlocked}>
              {approve.isPending ? <><span className="spinner" /> Committing…</> : actionLabel}
            </button>
          </div>
        </div>
      ) : null}

      {rejectOpen ? (
        <Modal
          title="Reject draft"
          onClose={() => setRejectOpen(false)}
          footer={
            <>
              <button className="btn" onClick={() => setRejectOpen(false)}>Cancel</button>
              <button
                className="btn btn-danger"
                disabled={reason.trim().length < 10 || reject.isPending}
                onClick={() => reject.mutate()}
              >
                {reject.isPending ? "Rejecting…" : "Reject with reason"}
              </button>
            </>
          }
        >
          <label className="field-label">Reason (required, at least 10 characters)</label>
          <textarea
            className="textarea small"
            placeholder="Explain why this draft is being rejected. The reason is audited."
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          {reason && reason.trim().length < 10 ? <div className="small muted mt-1">{10 - reason.trim().length} more characters required.</div> : null}
        </Modal>
      ) : null}
    </div>
  );
}

function ClaimLine({
  claim,
  emptyLabel = "Not documented",
  required = false,
}: {
  claim?: Claim | null;
  emptyLabel?: string;
  required?: boolean;
}) {
  if (!claim || !claim.text) {
    return (
      <div className="empty-field">
        {emptyLabel} — {required ? "required before signing." : "no source in the transcript."}
      </div>
    );
  }
  return (
    <div className="claim">
      <div className="claim-text">{claim.text}</div>
      <div className="claim-meta">
        {claim.human_authored ? (
          <span className="badge badge-neutral">Clinician-authored</span>
        ) : (
          <EvidenceChip eventIds={claim.source_event_ids} segmentIds={claim.source_segment_ids} />
        )}
        {claim.confidence !== undefined && claim.confidence < 0.85 ? (
          <span className="badge badge-warning">{Math.round(claim.confidence * 100)}% confidence</span>
        ) : null}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: any }) {
  return (
    <div className="mb-3">
      <div className="section-label">{title}</div>
      {children}
    </div>
  );
}

function ClaimList({ claims, emptyLabel }: { claims?: Claim[]; emptyLabel?: string }) {
  if (!claims?.length) return <div className="empty-field">{emptyLabel || "Not documented"}</div>;
  return <>{claims.map((claim, index) => <ClaimLine key={index} claim={claim} emptyLabel={emptyLabel} />)}</>;
}

function DraftContent({
  draft,
  selectedTasks,
  setSelectedTasks,
}: {
  draft: Draft;
  selectedTasks: number[];
  setSelectedTasks: (value: number[]) => void;
}) {
  const content = draft.content || {};
  switch (draft.feature) {
    case "F1":
      return (
        <>
          <Section title="Chief complaint"><ClaimLine claim={content.chief_complaint} /></Section>
          <Section title="History of presenting illness"><ClaimLine claim={content.hpi} /></Section>
          <Section title="Examination">
            <ClaimLine claim={content.exam?.general} emptyLabel="General examination not documented" />
            {content.exam?.systemic ? <ClaimLine claim={content.exam.systemic} /> : null}
          </Section>
          <Section title="Assessment"><ClaimList claims={content.assessment} /></Section>
          <Section title="Plan"><ClaimList claims={content.plan} /></Section>
          {content.medication_mentions?.length ? (
            <Section title="Medication mentions">
              <table className="table">
                <thead><tr><th>Drug</th><th>Dose</th><th>Frequency</th><th>Source</th></tr></thead>
                <tbody>
                  {content.medication_mentions.map((med: any, index: number) => (
                    <tr key={index}>
                      <td>{med.drug}</td>
                      <td className="mono">{med.dose || "—"}</td>
                      <td>{med.frequency || "—"}</td>
                      <td><EvidenceChip eventIds={med.source_event_ids} segmentIds={med.source_segment_ids} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Section>
          ) : null}
          <Section title="Follow-up"><ClaimLine claim={content.follow_up} /></Section>
          <NotDocumented items={content.not_documented} />
        </>
      );
    case "F2":
      return (
        <>
          <Section title="Chief complaint"><ClaimLine claim={content.chief_complaint} /></Section>
          <Section title="History"><ClaimLine claim={content.history} /></Section>
          <Section title="Examination">
            <ClaimLine claim={content.exam?.general} emptyLabel="Examination not documented" />
            {content.exam?.systemic ? <ClaimLine claim={content.exam.systemic} /> : null}
          </Section>
          <Section title="Assessment"><ClaimList claims={content.assessment} /></Section>
          <Section title="Plan"><ClaimList claims={content.plan} /></Section>
          {content.proposed_orders?.length ? (
            <Section title="Proposed orders — drafts only">
              <table className="table">
                <thead><tr><th>Order</th><th>Rationale</th></tr></thead>
                <tbody>
                  {content.proposed_orders.map((order: any, index: number) => (
                    <tr key={index}>
                      <td>{order.order}</td>
                      <td className="muted">{order.rationale}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Section>
          ) : null}
          <NotDocumented items={content.not_documented} />
        </>
      );
    case "F3":
      return (
        <>
          <Section title="Round note"><ClaimList claims={content.note_claims} /></Section>
          <Section title="Proposed nursing chart entries — committed on note approval">
            {content.nursing_entries?.length ? (
              <ClaimList claims={content.nursing_entries} />
            ) : (
              <div className="empty-field">No nursing-chart entries were proposed. Nothing will be written to the nursing chart.</div>
            )}
          </Section>
          <NotDocumented items={content.not_documented} />
        </>
      );
    case "F4":
      return (
        <>
          <Section title="Subjective"><ClaimLine claim={content.subjective} /></Section>
          <Section title="Objective"><ClaimLine claim={content.objective} /></Section>
          <Section title="Examination">
            <ClaimLine claim={content.exam?.general} emptyLabel="Examination not documented" required />
            {content.exam?.systemic ? <ClaimLine claim={content.exam.systemic} /> : null}
          </Section>
          <Section title="Assessment"><ClaimList claims={content.assessment} /></Section>
          <Section title="Plan"><ClaimLine claim={content.plan} emptyLabel="Plan not documented" required /></Section>
          <NotDocumented items={content.not_documented} />
        </>
      );
    case "F6":
      return (
        <>
          <Section title="Summary">{content.summary ? <p className="fs-13">{content.summary}</p> : null}</Section>
          <Section title="Discrepancies">
            {content.discrepancies?.map((item: any, index: number) => (
              <div className="alert-card mb-2" key={index} style={{ borderLeftColor: item.kind === "interaction" || item.kind === "contraindicated" ? "var(--critical)" : "var(--warning)" }}>
                <div className="flex items-center gap-2">
                  <span className={`badge ${item.kind === "interaction" || item.kind === "contraindicated" ? "badge-critical" : "badge-warning"}`}>{item.kind}</span>
                  <strong className="fs-13">{item.home_med}</strong>
                  <span className="small muted">→ {item.current_order || "not ordered"}</span>
                </div>
                <div className="alert-explanation">{item.explanation}</div>
                {item.field ? (
                  <div className="small muted">
                    {item.field}: home “{item.home_value || "—"}” → inpatient “{item.current_value || "—"}”
                  </div>
                ) : null}
                {item.recommended_action ? <div className="small"><strong>Recommended:</strong> {item.recommended_action}</div> : null}
                <EvidenceChip eventIds={item.evidence_event_ids} />
              </div>
            ))}
          </Section>
        </>
      );
    case "F7":
      return (
        <>
          <Section title="Shift window">
            <div className="small muted">{content.shift_window?.start} → {content.shift_window?.end}</div>
          </Section>
          <Section title="Assembly summary"><ClaimLine claim={content.summary} /></Section>
          <Section title="Flow-sheet entries">
            {content.entries?.length ? (
              <table className="table">
                <thead><tr><th>Category</th><th>Observation</th><th>Value</th><th>Recorded</th><th>Source</th></tr></thead>
                <tbody>
                  {content.entries.map((entry: any, index: number) => (
                    <tr key={`${entry.source_event_id}-${index}`}>
                      <td><span className="badge badge-neutral">{entry.category}</span></td>
                      <td>{entry.label}<div className="small muted">{entry.device}</div></td>
                      <td className="mono">{entry.value} {entry.unit}</td>
                      <td className="small muted">{entry.recorded_at?.replace("T", " ").slice(0, 16)}</td>
                      <td><EvidenceChip eventIds={entry.source_event_id ? [entry.source_event_id] : []} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="empty-field">No structured observations were available for this shift.</div>
            )}
          </Section>
          <NotDocumented items={content.not_documented} />
        </>
      );
    case "F9":
      return (
        <>
          {content.sections?.map((section: any, index: number) => (
            <Section title={section.heading} key={index}>
              <ClaimList claims={section.paragraphs} />
            </Section>
          ))}
          {content.medications?.length ? (
            <Section title="Discharge medications — assembled deterministically">
              {content.medications.some((med: any) => med.safety_status && med.safety_status !== "ok") ? (
                <div className="banner warning mb-2">
                  Some active orders carry an open safety alert. The list is carried from active orders for reconciliation; resolve the flagged items before any external use.
                </div>
              ) : null}
              <table className="table">
                <thead><tr><th>Drug</th><th>Dose</th><th>Route</th><th>Frequency</th><th>Safety</th><th>Source</th></tr></thead>
                <tbody>
                  {content.medications.map((med: any, index: number) => (
                    <tr key={index}>
                      <td>
                        {med.drug}
                        {med.safety_note ? <div className="small" style={{ color: "var(--critical)", maxWidth: 320 }}>{med.safety_note}</div> : null}
                      </td>
                      <td className="mono">{med.dose}</td>
                      <td>{med.route}</td>
                      <td>{med.frequency}</td>
                      <td>
                        <span className={`badge ${med.safety_status === "contraindicated" ? "badge-critical" : med.safety_status === "review" ? "badge-warning" : "badge-success"}`}>
                          {med.safety_status === "contraindicated" ? "alert" : med.safety_status === "review" ? "review" : "clear"}
                        </span>
                      </td>
                      <td><EvidenceChip eventIds={med.source_event_id ? [med.source_event_id] : []} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Section>
          ) : null}
          <Section title="Pending results">
            {content.pending_results?.length ? (
              <ClaimList claims={content.pending_results} />
            ) : (
              <div className="small muted">No unreviewed results at draft time.</div>
            )}
          </Section>
          <Section title="Follow-up"><ClaimList claims={content.follow_up} /></Section>
          <Section title="Red flags"><ClaimList claims={content.red_flags} /></Section>
          <NotDocumented items={content.not_documented} />
        </>
      );
    case "F10":
      return (
        <>
          <Section title="Request">
            <dl className="kv">
              <dt>Type</dt><dd>{content.request_type}</dd>
              <dt>Study</dt><dd>{content.study}</dd>
              <dt>Priority</dt><dd>{content.priority}</dd>
              <dt>Diagnosis</dt><dd>{content.diagnosis || "—"}</dd>
            </dl>
          </Section>
          <Section title="Clinical indication"><ClaimLine claim={content.indication} /></Section>
          <Section title="Instructions">
            <div className="small">{content.instructions || "No special instructions."}</div>
          </Section>
          <Section title="Allergies carried forward — verification required">
            {content.allergies_to_verify?.length ? (
              <table className="table">
                <thead><tr><th>Substance</th><th>Reaction</th><th>Status</th><th>Source</th></tr></thead>
                <tbody>
                  {content.allergies_to_verify.map((item: any, index: number) => (
                    <tr key={index}>
                      <td>{item.substance}</td>
                      <td>{item.reaction || "—"}</td>
                      <td><span className={`badge ${item.verified ? "badge-success" : "badge-warning"}`}>{item.verified ? "verified" : "unverified"}</span></td>
                      <td><EvidenceChip eventIds={item.source_event_id ? [item.source_event_id] : []} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="empty-field">No allergy is documented. Confirm this with the patient before a contrast or procedure request.</div>
            )}
          </Section>
          <div className="banner warning mt-3">Demo export only. No laboratory, radiology or external transmission exists in this build.</div>
        </>
      );
    case "F11":
      return (
        <>
          <Section title="Referral">
            <dl className="kv">
              <dt>Specialty</dt><dd>{content.specialty}</dd>
              <dt>Service</dt><dd>{content.specialist || "—"}</dd>
              <dt>Urgency</dt><dd>{content.urgency}</dd>
            </dl>
          </Section>
          <Section title="Clinical question"><ClaimLine claim={content.question} /></Section>
          <Section title="History"><ClaimLine claim={content.history} /></Section>
          <Section title="Relevant results"><ClaimList claims={content.relevant_results} emptyLabel="No abnormal results were attached" /></Section>
          <div className="banner warning mt-3">
            The model does not invent a specialist, appointment or response. Approval changes the demo status to sent; no external transmission occurs.
          </div>
        </>
      );
    case "F12":
      return (
        <>
          <Section title="Summary"><p className="fs-13">{content.summary}</p></Section>
          <Section title="Review gaps">
            {content.gaps?.map((gap: any, index: number) => (
              <div className="alert-card mb-2" key={index}>
                <span className="badge badge-warning">{gap.kind.replaceAll("_", " ")}</span>
                <div className="alert-explanation">{gap.description}</div>
                <EvidenceChip eventIds={gap.evidence_event_ids} />
              </div>
            ))}
          </Section>
          <div className="banner warning">Review queue only. No claim is submitted.</div>
        </>
      );
    case "F13":
      return (
        <>
          <Section title="Summary"><p className="fs-13">{content.summary}</p></Section>
          <Section title="Findings">
            {content.findings?.map((finding: any, index: number) => (
              <div className="alert-card mb-2" key={index}>
                <div className="flex items-center gap-2">
                  <span className={`badge ${finding.billing_status === "unsupported" ? "badge-critical" : "badge-warning"}`}>{finding.billing_status}</span>
                  <strong className="fs-13">{finding.procedure}</strong>
                </div>
                <div className="alert-explanation">{finding.explanation}</div>
                <EvidenceChip eventIds={finding.evidence_event_ids} />
              </div>
            ))}
          </Section>
          <div className="banner warning">Review queue only. Nothing is charged automatically.</div>
        </>
      );
    default:
      return <pre className="code" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(content, null, 2)}</pre>;
  }
}

function NotDocumented({ items }: { items?: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="not-documented">
      Also not documented: {items.map((item) => item.replaceAll("_", " ")).join(", ")}. The draft refuses to invent these fields.
    </div>
  );
}
