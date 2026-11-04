import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { get, post } from "../api";
import type { Draft, Lab, Meta } from "../types";
import { DraftReview } from "../components/DraftReview";
import { VoiceInput } from "../components/VoiceInput";
import { useCan, usePatientId } from "../session";
import { uploadReport } from "../features/f08/upload";
import IcuReadingForm from "../features/f07/IcuReadingForm";
import ReferralRequestForm from "../features/f11/ReferralRequestForm";
import { canAcknowledge, referralStatusLabel } from "../features/f11/rules";
import { ConsultNoteStatus, type ConsultGenerateResult } from "../features/f01/ConsultNoteStatus";
import { PageHeader } from "../components/PageHeader";
import { Stepper } from "../components/ui";
import type { StepState } from "../components/ui";

const CONSULT_TRANSCRIPT = `Doctor: Mr Menon, what brings you in today?
Ravi: My right leg has been swollen and red since Tuesday. It is warm and painful when I walk.
Doctor: Any fever?
Ravi: Yes, I felt feverish last night. No chest pain and no breathlessness.
Doctor: On examination the right lower leg is erythematous, warm and tender with a clear demarcation. No ulcer. Vitals are temperature 38.1, pulse 96, blood pressure 138 over 86, oxygen saturation 96 percent on room air.
Doctor: This looks like cellulitis. Given diabetes and CKD, I will admit for IV antibiotics and blood tests. We should stop metformin while renal function is checked. I will also check potassium today.
Ravi: Okay doctor.
Doctor: I will see you on the ward and review the creatinine and potassium results.`;

const ADMISSION_TRANSCRIPT = `Doctor: This is the admission assessment for Mr Ravi Menon, 58, referred from clinic with right lower leg cellulitis.
Ravi: The leg has been getting more red since Tuesday. I had fever last night and it hurts to walk.
Doctor: He has type 2 diabetes, hypertension, CKD stage 3b and atrial fibrillation. Penicillin allergy is documented as a rash.
Doctor: On examination he is febrile at 38.1, haemodynamically stable. The right lower leg has a demarcated area of erythema, warmth and tenderness, with no ulceration.
Doctor: Assessment is right lower leg cellulitis on a background of CKD. Plan is IV antibiotics with non-penicillin cover, renal monitoring and daily wound review.
Doctor: Please arrange creatinine, eGFR and potassium now and daily.`;

const ROUND_TRANSCRIPT = `Doctor: Continue IV flucloxacillin and review the leg tomorrow.
Doctor: Check potassium and renal function this morning.
Doctor: Stop metformin until renal function improves.
Doctor: Increase ibuprofen to 600 mg three times a day for the knee pain.
Nurse: I will chart the metformin hold and repeat observations at 2 pm.
Nurse: I will update the task list.`;

const PROGRESS_TRANSCRIPT = `Nurse: Overnight the patient slept poorly. Temperature came down to 37.4 after paracetamol. He reports less leg pain.
Doctor: No new breathlessness. I will review him on the ward round and complete the examination then.`;

const AUTO_DRAFT_DELAY_S = 3;
const MAX_REPORT_BYTES = 12 * 1024 * 1024;

type Tab = {
  key: string;
  label: string;
  feature: string;
  kind: "transcript" | "icu" | "referral" | "labs";
  title: string;
  description: string;
  transcript: string;
};

const TABS: Tab[] = [
  { key: "consult", label: "OPD consultation", feature: "F1", kind: "transcript", title: "OPD consultation", description: "Record or upload the consultation audio (with the patient's consent), or paste a transcript. The note drafts itself; you review, edit and sign it.", transcript: CONSULT_TRANSCRIPT },
  { key: "admission", label: "Admission assessment", feature: "F2", kind: "transcript", title: "Admission assessment", description: "MediBytes Analysis prepares the admission note from the interview. Verify the allergy record before approving; proposed orders stay as reports.", transcript: ADMISSION_TRANSCRIPT },
  { key: "round", label: "Ward round", feature: "F3", kind: "transcript", title: "Ward round", description: "Dictate the round. The note, nursing-chart entries and proposed tasks are drafted; you choose which tasks to create.", transcript: ROUND_TRANSCRIPT },
  { key: "progress", label: "Progress note", feature: "F4", kind: "transcript", title: "Progress notes", description: "MediBytes Analysis identifies what changed since the last note. Examination and plan must be written by the clinician before signing.", transcript: PROGRESS_TRANSCRIPT },
  { key: "icu", label: "ICU flow sheet", feature: "F7", kind: "icu", title: "ICU flow sheet", description: "Assembles device readings and structured observations into a flow sheet. It cannot add, estimate or silently round a value.", transcript: "" },
  { key: "referral", label: "Referral", feature: "F11", kind: "referral", title: "Referrals", description: "Prepares the right specialty, a specific clinical question and the documented history. A human approves before the referral status changes to sent.", transcript: "" },
  { key: "labs", label: "Lab results", feature: "—", kind: "labs", title: "Lab results", description: "Support view: review abnormal results and close the unreviewed-result alert.", transcript: "" },
];

type ICUEntry = {
  category: string;
  label: string;
  value: string;
  unit: string;
  recorded_at: string;
  device: string;
  source_event_id: string;
  confidence: number;
};

type Referral = {
  id: string;
  specialty: string;
  specialist: string;
  question: string;
  urgency: string;
  status: string;
  sent_at?: string | null;
  acknowledged_at?: string | null;
  completed_at?: string | null;
  response_summary?: string | null;
};

export function NotesPage() {
  const [params, setParams] = useSearchParams();
  const tabKey = params.get("tab") || "consult";
  const tab = TABS.find((item) => item.key === tabKey) || TABS[0];
  const queryClient = useQueryClient();
  const [transcript, setTranscript] = useState<string>(tab.transcript);
  const [error, setError] = useState("");
  const [consultResult, setConsultResult] = useState<ConsultGenerateResult | null>(null);
  const [transcribing, setTranscribing] = useState(false);
  // A transcript waiting out the short cancel window before it is drafted.
  const [pendingDraft, setPendingDraft] = useState<{ text: string; feature: string; left: number } | null>(null);
  const voiceFeatureRef = useRef("");
  const [labResult, setLabResult] = useState<any>(null);
  const canUpload = useCan("upload_document");

  useEffect(() => {
    setTranscript(tab.transcript);
    setError("");
    setConsultResult(null);
    setPendingDraft(null);
    setLabResult(null);
  }, [tab.key]);

  const hasDraft = tab.kind !== "labs";
  const draftQuery = useQuery<{ drafts: Draft[] }>({
    queryKey: ["drafts", tab.feature],
    queryFn: () => get<{ drafts: Draft[] }>(`/drafts?feature=${tab.feature}&limit=1`),
    enabled: hasDraft,
  });
  const labs = useQuery<{ labs: Lab[]; unreviewed: Lab[]; reviewed_count: number }>({
    queryKey: ["investigations"],
    queryFn: () => get("/investigations"),
    enabled: tab.kind === "labs",
  });
  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta"), refetchInterval: 30000 });
  // New readings go to the active encounter, so the sheet is read for that encounter too.
  const activeEncounterId = meta.data?.encounter.id ?? "";
  const icu = useQuery<{ entries: ICUEntry[]; shift_window: { start?: string; end?: string }; not_documented?: string[] }>({
    queryKey: ["icu-flow-sheet", activeEncounterId],
    queryFn: () => get(`/icu/flow-sheet?encounter_id=${encodeURIComponent(activeEncounterId)}`),
    enabled: tab.kind === "icu" && !!activeEncounterId,
  });
  const referrals = useQuery<{ referrals: Referral[] }>({
    queryKey: ["referrals"],
    queryFn: () => get("/referrals"),
    enabled: tab.kind === "referral",
  });
  const patientId = usePatientId();
  const consents = useQuery<{ consents: Array<{ id: string; granted: boolean; consent_type: string; occurred_at: string }> }>({
    queryKey: ["consents", "notes", patientId],
    queryFn: () => get(`/patients/${patientId}/consents`),
    enabled: tab.feature === "F1" && !!patientId,
  });
  const consentGranted = Boolean(consents.data?.consents?.some((entry) => entry.granted));

  const recordConsent = useMutation({
    mutationFn: () =>
      post(`/patients/${patientId}/consents`, {
        consent_type: "consultation_capture",
        granted: true,
        note: "Patient agrees to consultation capture for this episode.",
      }),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (err: any) => setError(String(err?.message || err)),
  });

  // A transcript from VoiceInput (recording or upload) lands in the textarea first, so nothing is lost
  // if drafting fails, then drafts after a short window in which the clinician can cancel.
  const onVoiceTranscript = (text: string) => {
    // The feature was pinned when transcription began; a transcript for another tab is dropped.
    if (voiceFeatureRef.current !== tab.feature) return;
    setTranscript(text);
    setError("");
    if (text.trim().length < 10) {
      setError("Transcript is too short to draft. Edit it and press Generate draft.");
      return;
    }
    setPendingDraft({ text, feature: tab.feature, left: AUTO_DRAFT_DELAY_S });
  };

  const generate = useMutation<any, Error, { text?: string } | undefined>({
    mutationFn: async (override) => {
      if (tab.kind === "transcript") {
        return post<any>("/notes/generate", {
          feature: tab.feature,
          transcript: override?.text ?? transcript,
          title: `${tab.title} transcript`,
        });
      }
      if (tab.kind === "icu") {
        return post<any>(`/icu/flow-sheet/generate?encounter_id=${encodeURIComponent(activeEncounterId)}`);
      }
      return null;
    },
    onSuccess: (result) => {
      setError("");
      setConsultResult(tab.feature === "F1" ? (result as ConsultGenerateResult | null) : null);
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  // Counts the cancel window down, then drafts. Editing the text, switching tab or leaving cancels it.
  useEffect(() => {
    if (!pendingDraft) return;
    if (pendingDraft.feature !== tab.feature) {
      setPendingDraft(null);
      return;
    }
    if (pendingDraft.left <= 0) {
      generate.mutate({ text: pendingDraft.text });
      setPendingDraft(null);
      return;
    }
    const timer = window.setTimeout(() => setPendingDraft((current) => (current ? { ...current, left: current.left - 1 } : current)), 1000);
    return () => window.clearTimeout(timer);
  }, [pendingDraft, tab.feature]);

  const uploadLab = useMutation({
    mutationFn: (file: File) => uploadReport(file, "lab_report"),
    onSuccess: (result: any) => {
      setError("");
      setLabResult(result);
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const chooseLabReport = (file: File | undefined) => {
    if (!file) return;
    setError("");
    setLabResult(null);
    const name = file.name.toLowerCase();
    const readable = file.type.startsWith("image/") || file.type === "application/pdf" || /\.(pdf|png|jpe?g|gif|webp|bmp|tiff?)$/.test(name);
    if (!readable) {
      setError("Choose a PDF or an image of the report.");
      return;
    }
    if (file.size > MAX_REPORT_BYTES) {
      setError("File too large (max 12 MB).");
      return;
    }
    uploadLab.mutate(file);
  };

  const reviewLab = useMutation({
    mutationFn: (eventId: string) => post(`/labs/${eventId}/review`),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const acknowledgeReferral = useMutation({
    mutationFn: (referralId: string) => post(`/referrals/${referralId}/acknowledge`, {}),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const completeReferral = useMutation({
    mutationFn: ({ referralId, summary }: { referralId: string; summary: string }) =>
      post(`/referrals/${referralId}/complete`, { response_summary: summary }),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const latest = draftQuery.data?.drafts?.[0];
  const tabChanged = (key: string) => {
    const next = TABS.find((item) => item.key === key) || TABS[0];
    setParams({ tab: key });
    setTranscript(next.transcript);
    setError("");
    setPendingDraft(null);
  };

  const intro = useMemo(() => {
    if (tab.kind === "icu") return "Readings from bedside devices, with units and times. Anything not recorded is shown as “not documented”, never guessed.";
    if (tab.kind === "referral") return "Drafts the specialist question and history. A clinician approves the referral before its status changes.";
    if (tab.kind === "labs") return "Laboratory results with reference ranges. Mark abnormal results as reviewed.";
    return tab.description;
  }, [tab]);

  const hasWorkflow = tab.kind === "transcript";

  const flowStage = !hasDraft || !latest ? 0 : latest.status === "approved" ? 3 : latest.status === "generating" ? 1 : 2;
  const flowSteps = ["Capture", "Draft", "Sign"].map((label, i) => ({
    label,
    state: (i < flowStage ? "done" : i === flowStage ? "current" : "todo") as StepState,
  }));
  const flowHint = [
    "Paste, record or upload what was said, then generate a draft.",
    "Drafting from the transcript. The draft appears on the right.",
    "Review the draft on the right, then approve it to sign.",
    "Signed and on the timeline. Generate again for a new version.",
  ][flowStage];

  return (
    <>
      <PageHeader
        title={tab.title}
        description={intro}
        meta={<span className="tag tag-ai">MediBytes Analysis \→ clinician review \→ sign</span>} />
      {hasWorkflow && (
        <div className="notes-flow">
          <Stepper steps={flowSteps} label="Note progress" />
          <span className="small muted">{flowHint}</span>
        </div>
      )}

      <div className="tabs">
        {TABS.map((item) => (
          <button key={item.key} className={`tab ${item.key === tab.key ? "active" : ""}`} onClick={() => tabChanged(item.key)}>
            {item.label}
          </button>
        ))}
      </div>

      <div className="split-main">
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">{tab.kind === "transcript" ? "1 · Input" : tab.kind === "labs" ? "Results" : tab.kind === "icu" ? "Device readings" : "Referral"}</div>
              <div className="card-sub">{tab.kind === "transcript" ? "Paste or record what was said, then generate a draft." : "Information from the patient record."}</div>
            </div>
          </div>
          <div className="card-pad">
            {error ? <div className="error-box mb-3">{error}</div> : null}

            {tab.kind === "transcript" ? (
              <>
                <label className="field-label">Conversation or dictation</label>
                <textarea
                  className="textarea"
                  value={transcript}
                  onChange={(event) => {
                    setTranscript(event.target.value);
                    setPendingDraft(null);
                  }}
                />
                {tab.feature === "F1" ? (
                  <div className={`banner ${consentGranted ? "success" : "warning"} mt-2`}>
                    <div className="flex items-center justify-between gap-2">
                      <span>
                        {consentGranted
                          ? "Consent is recorded. Record audio or upload an audio file; transcription needs the OpenAI key (live mode)."
                          : "Consent for consultation capture has not been recorded. Audio capture is blocked until it is."}
                      </span>
                      <div className="button-row">
                        {!consentGranted ? (
                          <button className="btn btn-sm" onClick={() => recordConsent.mutate()} disabled={recordConsent.isPending}>
                            {recordConsent.isPending ? "Recording consent…" : "Record consent"}
                          </button>
                        ) : null}
                        <VoiceInput
                          consentGranted={consentGranted}
                          disabled={generate.isPending || pendingDraft !== null}
                          onTranscribingChange={(active) => {
                            if (active) voiceFeatureRef.current = tab.feature;
                            setTranscribing(active);
                          }}
                          onTranscript={onVoiceTranscript}
                        />
                      </div>
                    </div>
                  </div>
                ) : null}
                {transcribing || pendingDraft || generate.isPending ? (
                  <div className="banner mt-2" role="status">
                    {transcribing ? (
                      <><span className="spinner" /> Transcribing...</>
                    ) : pendingDraft ? (
                      <div className="flex items-center justify-between gap-2">
                        <span>Drafting in {pendingDraft.left} s. The transcript is in the box above; you can edit it first.</span>
                        <button className="btn btn-sm" onClick={() => setPendingDraft(null)}>Cancel</button>
                      </div>
                    ) : (
                      <><span className="spinner" /> Drafting...</>
                    )}
                  </div>
                ) : null}
                <div className="button-row mt-2">
                  <button className="btn btn-primary" onClick={() => generate.mutate()} disabled={generate.isPending || transcript.trim().length < 10}>
                    {generate.isPending ? <><span className="spinner" /> Generating draft…</> : "Generate draft"}
                  </button>
                  <button className="btn" onClick={() => setTranscript(tab.transcript)}>Load consultation transcript</button>
                  {tab.feature === "F1" ? <span className="small muted">Paste text, record, or upload an audio file.</span> : <span className="small muted">Paste or type the text; this tab has no voice input.</span>}
                </div>
                {tab.feature === "F1" ? <ConsultNoteStatus result={consultResult} /> : null}
                {tab.feature === "F1" || tab.feature === "F2" ? (
                  <div className="banner mt-3">
                    Consent and allergy verification are captured separately below the draft. MediBytes Analysis cannot mark either as complete.
                  </div>
                ) : null}
              </>
            ) : null}

            {tab.kind === "icu" ? (
              <>
                <IcuReadingForm encounterId={activeEncounterId || undefined} />
                <div className="banner mb-3">
                  Source: device readings and entries recorded on this chart. {icu.data?.entries.length ?? 0} entries on the sheet.
                </div>
                <button className="btn btn-primary" onClick={() => generate.mutate()} disabled={generate.isPending}>
                  {generate.isPending ? <><span className="spinner" /> Assembling flow sheet…</> : "Assemble ICU flow sheet"}
                </button>
                <table className="table mt-3">
                  <thead><tr><th>Category</th><th>Observation</th><th>Value</th><th>Recorded</th><th>Source</th></tr></thead>
                  <tbody>
                    {icu.data?.entries.map((entry) => (
                      <tr key={entry.source_event_id}>
                        <td><span className="badge badge-neutral">{entry.category}</span></td>
                        <td>{entry.label}<div className="small muted">{entry.device}</div></td>
                        <td className="mono">{entry.value} {entry.unit}</td>
                        <td className="small muted">{entry.recorded_at?.replace("T", " ").slice(0, 16)}</td>
                        <td className="mono small">{entry.source_event_id}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {icu.data?.not_documented?.length ? (
                  <div className="small muted mt-2">Not documented: {icu.data.not_documented.join(", ")}</div>
                ) : null}
              </>
            ) : null}

            {tab.kind === "referral" ? (
              <>
                <div className="flex items-center justify-between mb-2">
                  <div className="card-sub">Referral queue · {referrals.data?.referrals.length ?? 0}</div>
                </div>
                <ReferralRequestForm />
                <div className="stack">
                  {referrals.data?.referrals.map((referral) => (
                    <div key={referral.id} className="list-card">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="strong">{referral.specialty}</div>
                          <div className="small muted">{referral.specialist || "Specialist service"} · {referral.urgency}</div>
                        </div>
                        <span className={`badge ${referral.status === "completed" ? "badge-success" : referral.status === "acknowledged" ? "badge-ai" : "badge-warning"}`}>{referralStatusLabel(referral.status)}</span>
                      </div>
                      <div className="small mt-2">{referral.question}</div>
                      <div className="button-row mt-2">
                        {canAcknowledge(referral.status) ? (
                          <button className="btn btn-sm" onClick={() => acknowledgeReferral.mutate(referral.id)} disabled={acknowledgeReferral.isPending}>Mark acknowledged</button>
                        ) : null}
                        {referral.status === "acknowledged" ? (
                          <button className="btn btn-sm" onClick={() => {
                            const summary = window.prompt("Specialist response summary");
                            if (summary) completeReferral.mutate({ referralId: referral.id, summary });
                          }} disabled={completeReferral.isPending}>Record response</button>
                        ) : null}
                      </div>
                      {referral.response_summary ? <div className="small muted mt-2">Response: {referral.response_summary}</div> : null}
                    </div>
                  ))}
                  {!referrals.data?.referrals.length ? <div className="small muted">No referrals yet.</div> : null}
                </div>
              </>
            ) : null}

            {tab.kind === "labs" ? (
              <>
                <div className="flex items-center justify-between mb-2">
                  <div className="card-sub">Latest results · {labs.data?.reviewed_count ?? 0} reviewed</div>
                  <label
                    className="btn btn-primary btn-sm"
                    title={canUpload ? undefined : "Your role cannot upload documents"}
                    style={canUpload ? undefined : { opacity: 0.5, pointerEvents: "none" }}
                  >
                    Upload lab report
                    <input
                      type="file"
                      accept="image/*,application/pdf"
                      style={{ display: "none" }}
                      disabled={!canUpload || uploadLab.isPending}
                      onChange={(event) => {
                        chooseLabReport(event.target.files?.[0]);
                        event.target.value = "";
                      }}
                    />
                  </label>
                </div>
                {uploadLab.isPending ? <div className="banner mb-2" role="status"><span className="spinner" /> Reading report...</div> : null}
                {labResult ? (
                  <div className={`banner ${labResult.ocr_status === "confirmed" || labResult.auto_committed ? "success" : "warning"} mb-2`} role="status">
                    {labResult.ocr_status === "confirmed" || labResult.auto_committed ? (
                      <div>
                        Saved {Array.isArray(labResult.labs) ? labResult.labs.length : labResult.extracted?.fields?.length ?? 0} result(s) from {labResult.filename} to the record as unreviewed. They are in the table below; a doctor still reviews each one.
                      </div>
                    ) : labResult.ocr_status === "needs_manual_entry" ? (
                      <div>
                        No text could be read from {labResult.filename}. Type the values from the original in Documents. <Link to="/documents?tab=inbound">Review in Documents</Link>
                      </div>
                    ) : labResult.ocr_status === "needs_confirmation" ? (
                      <div>
                        Some values in {labResult.filename} are low confidence. Confirm them in Documents before they are saved. <Link to="/documents?tab=inbound">Review in Documents</Link>
                      </div>
                    ) : (
                      <div>
                        <div>Read {labResult.extracted?.fields?.length ?? 0} value(s) from {labResult.filename}. Nothing is saved yet. <Link to="/documents?tab=inbound">Review in Documents</Link></div>
                        {labResult.auto_commit_error ? <div className="small mt-1">Automatic save did not complete: {String(labResult.auto_commit_error)}</div> : null}
                      </div>
                    )}
                    {!(labResult.ocr_status === "confirmed" || labResult.auto_committed) && labResult.extracted?.fields?.length ? (
                      <table className="table mt-2">
                        <thead><tr><th>Test</th><th>Value</th><th>Reference</th><th>Confidence</th></tr></thead>
                        <tbody>
                          {labResult.extracted.fields.map((field: any, index: number) => (
                            <tr key={`${field.name}-${index}`}>
                              <td>{field.name}</td>
                              <td className="mono">{field.value} {field.unit}</td>
                              <td className="mono small muted">{field.reference_range || "—"}</td>
                              <td>{Math.round((field.confidence ?? 0) * 100)}%</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : null}
                  </div>
                ) : null}
                <table className="table">
                  <thead><tr><th>Test</th><th>Value</th><th>Reference</th><th>Status</th><th /></tr></thead>
                  <tbody>
                    {labs.data?.labs.map((lab) => (
                      <tr key={lab.event_id}>
                        <td>{lab.name}</td>
                        <td className="mono">{lab.value} {lab.unit}</td>
                        <td className="mono small muted">{lab.reference_range}</td>
                        <td>
                          <span className={`badge ${lab.review_status === "unreviewed" ? "badge-warning" : "badge-success"}`}>
                            {lab.review_status === "unreviewed" ? "unreviewed" : "reviewed"}
                          </span>
                        </td>
                        <td className="right">
                          {lab.review_status === "unreviewed" ? (
                            <button className="btn btn-sm" onClick={() => reviewLab.mutate(lab.event_id)} disabled={reviewLab.isPending}>
                              Mark reviewed
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="small muted mt-2">
                  Marking a result reviewed resolves the unreviewed-result alert and is audited.
                </div>
              </>
            ) : null}
          </div>
        </div>

        <div>
          {latest && hasDraft ? (
            <DraftReview draft={latest} />
          ) : (
            <div className="card empty">
              <div className="empty-title">{hasDraft ? "No draft for this module yet." : "Support view"}</div>
              <div>{hasDraft ? "Generate one from the input panel. The draft will appear here with evidence attached." : "Review results in the table and mark abnormal ones as reviewed."}</div>
            </div>
          )}
          {latest?.status === "approved" && hasDraft ? (
            <div className="banner success mt-3">
              This version is approved and on the timeline. Generate again to create a new draft; the previous version will be marked superseded.
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}
