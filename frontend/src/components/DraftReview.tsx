import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post } from "../api";
import type { Claim, Draft, Meta } from "../types";
import { EvidenceChip } from "./Evidence";
import { Modal } from "./Modal";
import { Icon } from "./icons";
import { Banner, Field, MetaChip, Pill } from "./ui";
import type { Tone } from "./ui";

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

  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta") });
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
        approved_by: meta.data?.user.name || "Dr. Meera Shah",
      });
    },
    onSuccess: () => {
      setError("");
      invalidate();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const reject = useMutation({
    mutationFn: () => post<any>(`/drafts/${draft.id}/reject`, { reason, actor: meta.data?.user.name }),
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
      return patch<any>(`/drafts/${draft.id}`, { content: parsed, editor: meta.data?.user.name });
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
      return patch<any>(`/drafts/${draft.id}`, { content, editor: meta.data?.user.name });
    },
    onSuccess: () => {
      setError("");
      invalidate();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const accept = useMutation({
    mutationFn: () => post<any>(`/drafts/${draft.id}/accept-tasks`, { indices: selectedTasks, actor: meta.data?.user.name }),
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
        actor: meta.data?.user.name,
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
        actor: meta.data?.user.name,
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
  // F2 admission notes and F10 investigation requests both carry allergies that a clinician must verify;
  // the backend refuses approval of either until every one is verified.
  const verifiesAllergies = draft.feature === "F2" || draft.feature === "F10";
  const f2Unverified =
    verifiesAllergies &&
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

  // UI-only derived values for the render below (no new gating logic: every flag comes from the values above).
  const isClosed = isApproved || isRejected;
  const statusTone = isApproved ? "success" : isRejected ? "critical" : "ai";
  const statusLabel = isApproved ? "Approved" : isRejected ? "Rejected" : draft.status === "human_edited" ? "Human edited" : "AI draft";
  const allergyItems: any[] = verifiesAllergies ? draft.content?.allergies_to_verify || [] : [];
  const showConsentGate = draft.feature === "F1";
  const showAllergyGate = verifiesAllergies && allergyItems.length > 0;
  const showF4Gate = draft.feature === "F4" && !editMode && !isApproved && !isRejected;
  const gateStates: boolean[] = [
    ...(showConsentGate ? [!f1NoConsent] : []),
    ...(showAllergyGate ? allergyItems.map((item: any) => Boolean(item.verified)) : []),
    ...(showF4Gate ? [!f4Incomplete] : []),
  ];
  const gatesDone = gateStates.filter(Boolean).length;
  const gatesClear = gatesDone === gateStates.length;
  const blockReason = f4Incomplete
    ? "Examination and plan are required. Document them under Before you sign."
    : f2Unverified
      ? "Verify the documented allergy under Before you sign. A model may not mark an allergy as verified."
      : f1NoConsent
        ? "Record the patient's consent for consultation capture before signing."
        : "";

  return (
    <div className={`draft-shell ${isApproved ? "draft-approved" : ""} ${isRejected ? "draft-rejected" : ""}`}>
      <div className="draft-head">
        <div className="draft-head-text">
          <div className="draft-title-row">
            <h3 className="draft-title">{FEATURE_LABELS[draft.feature] || draft.feature}</h3>
            <Pill tone={statusTone} icon={isApproved ? "check" : isRejected ? "close" : "spark"}>{statusLabel}</Pill>
          </div>
          <div className="draft-meta">
            <MetaChip icon="spark" title="Model">{draft.model}</MetaChip>
            <MetaChip title="Prompt version">prompt {draft.prompt_version}</MetaChip>
            <MetaChip icon="link" title="Timeline events this draft cites">
              {draft.evidence_event_ids.length} source{draft.evidence_event_ids.length === 1 ? "" : "s"}
            </MetaChip>
            {draft.edited_by ? <MetaChip icon="user">edited by {draft.edited_by}</MetaChip> : null}
          </div>
        </div>
        {!isApproved && !isRejected ? (
          <button className="btn btn-sm" aria-pressed={editMode} onClick={() => setEditMode((value) => !value)}>
            <Icon name="edit" size={14} />
            {editMode ? "Stop editing" : "Edit draft (advanced)"}
          </button>
        ) : null}
      </div>

      {error ? <div className="error-box draft-error" role="alert">{error}</div> : null}

      {showConsentGate || showAllergyGate || showF4Gate ? (
        <section className={`draft-gates ${gatesClear ? "is-clear" : ""}`} aria-label={isClosed ? "Sign-off checks" : "Before you sign"}>
          <div className="draft-gates-title">
            <Icon name={gatesClear ? "check" : "alert"} size={16} />
            {isClosed ? "Sign-off checks" : "Before you sign"}
            <span className="draft-gates-count">{gatesDone} of {gateStates.length} done</span>
          </div>
          <div className="draft-gates-sub">Explicit clinician actions. The model cannot complete these for you.</div>

          {showConsentGate ? (
            <div className="draft-gate">
              <GateMark ok={!f1NoConsent} />
              <div className="draft-gate-text">
                <div className="draft-gate-label">Consent for consultation capture</div>
                <div className="draft-gate-hint">
                  {f1NoConsent
                    ? "Not recorded yet. The model cannot record it for you."
                    : "Recorded and audited."}
                </div>
              </div>
              {f1NoConsent ? (
                <button
                  className="btn btn-sm"
                  onClick={() => recordConsent.mutate()}
                  disabled={recordConsent.isPending}
                  aria-busy={recordConsent.isPending || undefined}
                >
                  {recordConsent.isPending ? <><span className="spinner" /> Recording…</> : "Record consent"}
                </button>
              ) : null}
            </div>
          ) : null}

          {showAllergyGate
            ? allergyItems.map((item: any, index: number) => (
                <div className="draft-gate" key={`${item.substance}-${index}`}>
                  <GateMark ok={Boolean(item.verified)} />
                  <div className="draft-gate-text">
                    <div className="draft-gate-label">Allergy: {item.substance}</div>
                    <div className="draft-gate-hint">Reaction: {item.reaction || "not recorded"}</div>
                  </div>
                  <Pill tone={item.verified ? "success" : "warning"}>{item.verified ? "verified" : "unverified"}</Pill>
                  <EvidenceChip eventIds={item.source_event_id ? [item.source_event_id] : []} />
                  {!item.verified && !isApproved && !isRejected ? (
                    <button
                      className="btn btn-sm"
                      onClick={() => verifyAllergy.mutate(item.substance)}
                      disabled={verifyAllergy.isPending}
                      aria-busy={(verifyAllergy.isPending && verifyAllergy.variables === item.substance) || undefined}
                    >
                      {verifyAllergy.isPending && verifyAllergy.variables === item.substance ? <><span className="spinner" /> Verify</> : "Verify"}
                    </button>
                  ) : null}
                </div>
              ))
            : null}

          {showF4Gate ? (
            <div className="draft-gate">
              <GateMark ok={!f4Incomplete} />
              <div className="draft-gate-text">
                <div className="draft-gate-label">Examination and plan (clinician-authored)</div>
                <div className="draft-gate-hint">
                  The draft will not invent examination findings or a plan. What you type is attributed to you,
                  not to the transcript.
                </div>
              </div>
              <div className="draft-gate-body">
                <Field label="Examination" htmlFor={`f4-exam-${draft.id}`}>
                  <textarea
                    id={`f4-exam-${draft.id}`}
                    className="textarea small"
                    placeholder="e.g. Right lower leg erythema reduced; chest clear; no pedal oedema."
                    value={f4Exam}
                    onChange={(event) => setF4Exam(event.target.value)}
                  />
                </Field>
                <Field label="Plan" htmlFor={`f4-plan-${draft.id}`}>
                  <textarea
                    id={`f4-plan-${draft.id}`}
                    className="textarea small"
                    placeholder="e.g. Continue IV flucloxacillin; hold metformin; repeat renal panel tomorrow."
                    value={f4Plan}
                    onChange={(event) => setF4Plan(event.target.value)}
                  />
                </Field>
                <div className="button-row">
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => saveF4.mutate()}
                    disabled={!f4Exam.trim() || !f4Plan.trim() || saveF4.isPending}
                    aria-busy={saveF4.isPending || undefined}
                  >
                    {saveF4.isPending ? <><span className="spinner" /> Saving…</> : "Save clinician documentation"}
                  </button>
                  {saveF4.isSuccess ? <span className="small muted" role="status">Saved as human-authored and audited.</span> : null}
                </div>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      <div className="draft-body">
        {isApproved ? (
          <div className="mb-3">
            <Banner tone="success">
              Committed to the timeline by {draft.approved_by || "clinician"}
              {draft.committed_event_id ? <span className="mono"> · {draft.committed_event_id}</span> : null}
            </Banner>
          </div>
        ) : null}
        {isRejected ? (
          <div className="mb-3">
            <Banner tone="danger">Rejected: {draft.rejected_reason}</Banner>
          </div>
        ) : null}

        <article className="draft-paper">
          {editMode ? (
            <div className="draft-editing">
              <label className="field-label" htmlFor={`draft-json-${draft.id}`}>Draft content (JSON)</label>
              <div className="field-hint mb-2">
                Edit the validated JSON. Saving re-validates the draft and marks it human-edited.
              </div>
              <textarea
                id={`draft-json-${draft.id}`}
                className="textarea"
                value={editText}
                onChange={(event) => setEditText(event.target.value)}
              />
              <div className="button-row mt-2">
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => saveEdit.mutate()}
                  disabled={saveEdit.isPending}
                  aria-busy={saveEdit.isPending || undefined}
                >
                  {saveEdit.isPending ? <><span className="spinner" /> Saving…</> : "Save edits"}
                </button>
              </div>
            </div>
          ) : (
            <DraftContent draft={draft} selectedTasks={selectedTasks} setSelectedTasks={setSelectedTasks} />
          )}
        </article>

        {draft.feature === "F3" && tasks.length ? (
          <section className="draft-tasks" aria-label="Proposed tasks">
            <h4 className="draft-section-title">
              Proposed tasks<span className="draft-section-sub">Choose what becomes real</span>
            </h4>
            <div className="rows">
              {tasks.map((task, index) => {
                const checked = selectedTasks.includes(index);
                return (
                  <label className={`lrow draft-task ${checked ? "selected" : ""}`} key={`${task.title}-${index}`}>
                    <input
                      className="checkbox"
                      type="checkbox"
                      checked={checked}
                      onChange={(event) => {
                        setSelectedTasks((current) =>
                          event.target.checked ? [...current, index] : current.filter((item) => item !== index),
                        );
                      }}
                    />
                    <span className="lrow-main">
                      <span className="lrow-title">{task.title}</span>
                      <span className="lrow-chips">
                        <Pill tone={priorityTone(task.priority)}>{task.priority}</Pill>
                        <MetaChip icon="clock">due in {task.due_in_hours}h</MetaChip>
                        <MetaChip>{Math.round((task.confidence ?? 1) * 100)}% confidence</MetaChip>
                      </span>
                    </span>
                    <span className="lrow-side">
                      <EvidenceChip eventIds={[]} segmentIds={task.source_segment_ids} />
                    </span>
                  </label>
                );
              })}
            </div>
            <div className="button-row mt-3">
              <button
                className="btn btn-primary btn-sm"
                disabled={!isApproved || accept.isPending || !selectedTasks.length}
                onClick={() => accept.mutate()}
                aria-busy={accept.isPending || undefined}
              >
                {accept.isPending
                  ? <><span className="spinner" /> Accepting…</>
                  : `Accept ${selectedTasks.length} selected task${selectedTasks.length === 1 ? "" : "s"}`}
              </button>
              {!isApproved ? <span className="small muted">Approve the note first, then accept tasks.</span> : null}
            </div>
            {accept.isSuccess ? <div className="success-box mt-2" role="status">Tasks accepted. They are now real work items.</div> : null}
          </section>
        ) : null}
      </div>

      {!isApproved && !isRejected ? (
        <div className="draft-actions">
          {blockReason ? (
            <div className="draft-block-reason" role="status">
              <Icon name="alert" size={14} />
              {blockReason}
            </div>
          ) : (
            <div className="small muted">Nothing is written until you approve. Every commit is audited.</div>
          )}
          <div className="button-row">
            <button className="btn btn-danger btn-sm" onClick={() => setRejectOpen(true)}>
              Reject
            </button>
            <button
              className="btn btn-primary"
              onClick={() => approve.mutate()}
              disabled={approve.isPending || approvalBlocked}
              title={approvalBlocked ? blockReason : undefined}
              aria-busy={approve.isPending || undefined}
            >
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

function GateMark({ ok }: { ok: boolean }) {
  return (
    <span className={`check-mark ${ok ? "ok" : "bad"}`}>
      <Icon name={ok ? "check" : "alert"} size={12} />
      <span className="sr-only">{ok ? "Done" : "To do"}</span>
    </span>
  );
}

function priorityTone(priority: unknown): Tone {
  const value = String(priority || "").toLowerCase();
  if (/stat|urgent|critical|immediate/.test(value)) return "critical";
  if (/high/.test(value)) return "warning";
  return "neutral";
}

/** Shown in a table cell or quoted value when the source carries nothing. */
function Blank({ label = "Not recorded" }: { label?: string }) {
  return <span className="muted">{label}</span>;
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
        {emptyLabel}: {required ? "required before signing." : "no source in the transcript."}
      </div>
    );
  }
  return (
    <div className="claim">
      <div className="claim-text">{claim.text}</div>
      <div className="claim-meta">
        {claim.human_authored ? (
          <Pill tone="neutral" icon="user">Clinician-authored</Pill>
        ) : (
          <EvidenceChip eventIds={claim.source_event_ids} segmentIds={claim.source_segment_ids} />
        )}
        {claim.confidence !== undefined && claim.confidence < 0.85 ? (
          <Pill tone="warning">{Math.round(claim.confidence * 100)}% confidence</Pill>
        ) : null}
      </div>
    </div>
  );
}

function Section({ title, sub, children }: { title: string; sub?: string; children: any }) {
  return (
    <section className="draft-section">
      <h4 className="draft-section-title">
        {title}
        {sub ? <span className="draft-section-sub">{sub}</span> : null}
      </h4>
      {children}
    </section>
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
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Drug</th><th>Dose</th><th>Frequency</th><th>Source</th></tr></thead>
                  <tbody>
                    {content.medication_mentions.map((med: any, index: number) => (
                      <tr key={index}>
                        <td>{med.drug}</td>
                        <td className="mono">{med.dose || <Blank />}</td>
                        <td>{med.frequency || <Blank />}</td>
                        <td><EvidenceChip eventIds={med.source_event_ids} segmentIds={med.source_segment_ids} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
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
            <Section title="Proposed orders" sub="Drafts only">
              <div className="table-wrap">
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
              </div>
            </Section>
          ) : null}
          <NotDocumented items={content.not_documented} />
        </>
      );
    case "F3":
      return (
        <>
          <Section title="Round note"><ClaimList claims={content.note_claims} /></Section>
          <Section title="Proposed nursing chart entries" sub="Committed on note approval">
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
            {content.discrepancies?.map((item: any, index: number) => {
              const severe = item.kind === "interaction" || item.kind === "contraindicated";
              return (
                <div className={`alert-card ${severe ? "critical" : "warning"} mb-2`} key={index}>
                  <span className="alert-icon" aria-hidden="true"><Icon name="pill" size={18} /></span>
                  <div className="flex items-center flex-wrap gap-2">
                    <Pill tone={severe ? "critical" : "warning"}>{item.kind}</Pill>
                    <strong className="fs-13">{item.home_med}</strong>
                    <span className="small muted">→ {item.current_order || "not ordered"}</span>
                  </div>
                  <div className="alert-explanation">{item.explanation}</div>
                  {item.field ? (
                    <div className="small muted">
                      {item.field}: home “{item.home_value || "not recorded"}” → inpatient “{item.current_value || "not recorded"}”
                    </div>
                  ) : null}
                  {item.recommended_action ? <div className="alert-action"><strong>Recommended:</strong> {item.recommended_action}</div> : null}
                  <div className="mt-2"><EvidenceChip eventIds={item.evidence_event_ids} /></div>
                </div>
              );
            })}
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
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Category</th><th>Observation</th><th>Value</th><th>Recorded</th><th>Source</th></tr></thead>
                  <tbody>
                    {content.entries.map((entry: any, index: number) => (
                      <tr key={`${entry.source_event_id}-${index}`}>
                        <td><Pill tone="neutral">{entry.category}</Pill></td>
                        <td>{entry.label}<div className="small muted">{entry.device}</div></td>
                        <td className="mono">{entry.value} {entry.unit}</td>
                        <td className="small muted">{entry.recorded_at?.replace("T", " ").slice(0, 16)}</td>
                        <td><EvidenceChip eventIds={entry.source_event_id ? [entry.source_event_id] : []} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
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
            <Section title="Discharge medications" sub="Assembled deterministically">
              {content.medications.some((med: any) => med.safety_status && med.safety_status !== "ok") ? (
                <div className="mb-2">
                  <Banner tone="warning">
                    Some active orders carry an open safety alert. The list is carried from active orders for reconciliation; resolve the flagged items before any external use.
                  </Banner>
                </div>
              ) : null}
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Drug</th><th>Dose</th><th>Route</th><th>Frequency</th><th>Safety</th><th>Source</th></tr></thead>
                  <tbody>
                    {content.medications.map((med: any, index: number) => (
                      <tr key={index}>
                        <td>
                          {med.drug}
                          {med.safety_note ? <div className="small draft-med-note">{med.safety_note}</div> : null}
                        </td>
                        <td className="mono">{med.dose}</td>
                        <td>{med.route}</td>
                        <td>{med.frequency}</td>
                        <td>
                          <Pill tone={med.safety_status === "contraindicated" ? "critical" : med.safety_status === "review" ? "warning" : "success"}>
                            {med.safety_status === "contraindicated" ? "alert" : med.safety_status === "review" ? "review" : "clear"}
                          </Pill>
                        </td>
                        <td><EvidenceChip eventIds={med.source_event_id ? [med.source_event_id] : []} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
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
              <dt>Diagnosis</dt><dd>{content.diagnosis || <Blank />}</dd>
            </dl>
          </Section>
          <Section title="Clinical indication"><ClaimLine claim={content.indication} /></Section>
          <Section title="Instructions">
            <div className="small">{content.instructions || "No special instructions."}</div>
          </Section>
          <Section title="Allergies carried forward" sub="Verification required">
            {content.allergies_to_verify?.length ? (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Substance</th><th>Reaction</th><th>Status</th><th>Source</th></tr></thead>
                  <tbody>
                    {content.allergies_to_verify.map((item: any, index: number) => (
                      <tr key={index}>
                        <td>{item.substance}</td>
                        <td>{item.reaction || <Blank />}</td>
                        <td><Pill tone={item.verified ? "success" : "warning"}>{item.verified ? "verified" : "unverified"}</Pill></td>
                        <td><EvidenceChip eventIds={item.source_event_id ? [item.source_event_id] : []} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty-field">No allergy is documented. Confirm this with the patient before a contrast or procedure request.</div>
            )}
          </Section>
          <div className="mt-3">
            <Banner tone="warning">Demo export only. No laboratory, radiology or external transmission exists in this build.</Banner>
          </div>
        </>
      );
    case "F11":
      return (
        <>
          <Section title="Referral">
            <dl className="kv">
              <dt>Specialty</dt><dd>{content.specialty}</dd>
              <dt>Service</dt><dd>{content.specialist || <Blank label="Not named" />}</dd>
              <dt>Urgency</dt><dd>{content.urgency}</dd>
            </dl>
          </Section>
          <Section title="Clinical question"><ClaimLine claim={content.question} /></Section>
          <Section title="History"><ClaimLine claim={content.history} /></Section>
          <Section title="Relevant results"><ClaimList claims={content.relevant_results} emptyLabel="No abnormal results were attached" /></Section>
          <div className="mt-3">
            <Banner tone="warning">
              The model does not invent a specialist, appointment or response. Approval changes the demo status to sent; no external transmission occurs.
            </Banner>
          </div>
        </>
      );
    case "F12":
      return (
        <>
          <Section title="Summary"><p className="fs-13">{content.summary}</p></Section>
          <Section title="Review gaps">
            {content.gaps?.map((gap: any, index: number) => (
              <div className="alert-card warning mb-2" key={index}>
                <span className="alert-icon" aria-hidden="true"><Icon name="billing" size={18} /></span>
                <div><Pill tone="warning">{gap.kind.replaceAll("_", " ")}</Pill></div>
                <div className="alert-explanation">{gap.description}</div>
                <div><EvidenceChip eventIds={gap.evidence_event_ids} /></div>
              </div>
            ))}
          </Section>
          <div className="mt-3">
            <Banner tone="warning">Review queue only. No claim is submitted.</Banner>
          </div>
        </>
      );
    case "F13":
      return (
        <>
          <Section title="Summary"><p className="fs-13">{content.summary}</p></Section>
          <Section title="Findings">
            {content.findings?.map((finding: any, index: number) => {
              const unsupported = finding.billing_status === "unsupported";
              return (
                <div className={`alert-card ${unsupported ? "critical" : "warning"} mb-2`} key={index}>
                  <span className="alert-icon" aria-hidden="true"><Icon name="leakage" size={18} /></span>
                  <div className="flex items-center flex-wrap gap-2">
                    <Pill tone={unsupported ? "critical" : "warning"}>{finding.billing_status}</Pill>
                    <strong className="fs-13">{finding.procedure}</strong>
                  </div>
                  <div className="alert-explanation">{finding.explanation}</div>
                  <div><EvidenceChip eventIds={finding.evidence_event_ids} /></div>
                </div>
              );
            })}
          </Section>
          <div className="mt-3">
            <Banner tone="warning">Review queue only. Nothing is charged automatically.</Banner>
          </div>
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
