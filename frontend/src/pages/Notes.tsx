import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { get, post, transcribeAudio } from "../api";
import type { Draft, Lab } from "../types";
import { DraftReview } from "../components/DraftReview";
import { usePatientId } from "../session";

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
  { key: "consult", label: "Consultation · F1", feature: "F1", kind: "transcript", title: "Ambient consultation note", description: "Record or paste the consultation. The note drafts itself and waits for your signature.", transcript: CONSULT_TRANSCRIPT },
  { key: "admission", label: "Admission · F2", feature: "F2", kind: "transcript", title: "Admission assessment", description: "Draft an H&P from the referral interview. Proposed orders and allergy verification stay open until a clinician acts.", transcript: ADMISSION_TRANSCRIPT },
  { key: "round", label: "Round · F3", feature: "F3", kind: "transcript", title: "Ward round handover", description: "Dictate the round. Instructions become proposed tasks and proposed nursing-chart entries you can accept or reject.", transcript: ROUND_TRANSCRIPT },
  { key: "progress", label: "Progress · F4", feature: "F4", kind: "transcript", title: "Daily progress note", description: "The module refuses to invent examination findings or a plan. Missing sections stay visibly empty.", transcript: PROGRESS_TRANSCRIPT },
  { key: "icu", label: "ICU chart · F7", feature: "F7", kind: "icu", title: "ICU flow sheet", description: "Assembles device readings and structured observations into a flow sheet. It cannot add, estimate or silently round a value.", transcript: "" },
  { key: "referral", label: "Referral · F11", feature: "F11", kind: "referral", title: "Smart referral", description: "Drafts the right specialty, a specific clinical question and the documented history. A human approves before the demo status changes to sent.", transcript: "" },
  { key: "labs", label: "Labs (support)", feature: "—", kind: "labs", title: "Laboratory results", description: "Support view: review abnormal results and close the unreviewed-result alert. This is not the F11 PRD module.", transcript: "" },
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
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    setTranscript(tab.transcript);
    setError("");
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
  const icu = useQuery<{ entries: ICUEntry[]; shift_window: { start?: string; end?: string } }>({
    queryKey: ["icu-flow-sheet"],
    queryFn: () => get("/icu/flow-sheet"),
    enabled: tab.kind === "icu",
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

  const startRecording = async () => {
    setError("");
    if (!consentGranted) {
      setError("Record patient consent before capturing audio.");
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Audio capture is not available in this browser. Paste the seeded transcript instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        setTranscribing(true);
        try {
          const result = await transcribeAudio(blob);
          setTranscript(result.text);
          setError("");
        } catch (err: any) {
          setError(String(err?.message || err));
        } finally {
          setTranscribing(false);
        }
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch (err: any) {
      setError(`Microphone unavailable: ${String(err?.message || err)}`);
    }
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
    setRecording(false);
  };

  const generate = useMutation({
    mutationFn: async () => {
      if (tab.kind === "transcript") {
        return post<any>("/notes/generate", {
          feature: tab.feature,
          transcript,
          title: `${tab.title} transcript`,
        });
      }
      if (tab.kind === "icu") {
        return post<any>("/icu/flow-sheet/generate");
      }
      if (tab.kind === "referral") {
        return post<any>("/referrals/generate", {});
      }
      return null;
    },
    onSuccess: () => {
      setError("");
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

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
  };

  const intro = useMemo(() => {
    if (tab.kind === "icu") return "F7 reads structured device feeds. A missing section is listed as not documented, not guessed.";
    if (tab.kind === "referral") return "F11 picks the specialty and the question. The clinician still decides whether to sign and send.";
    if (tab.kind === "labs") return "Supporting laboratory review; the PRD's F11 is the smart-referral workflow.";
    return "Every claim in the draft carries a source event or transcript segment. Nothing writes until approval.";
  }, [tab]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Clinical notes</h1>
          <div className="page-sub">{intro}</div>
        </div>
        <div className="page-actions">
          <span className="badge badge-ai">draft → review → sign</span>
        </div>
      </div>

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
              <div className="card-title">{tab.title}</div>
              <div className="card-sub">{tab.description}</div>
            </div>
            <span className="badge badge-neutral">{tab.feature}</span>
          </div>
          <div className="card-pad">
            {error ? <div className="error-box mb-3">{error}</div> : null}

            {tab.kind === "transcript" ? (
              <>
                <label className="field-label">Consultation input</label>
                <textarea className="textarea" value={transcript} onChange={(event) => setTranscript(event.target.value)} />
                {tab.feature === "F1" ? (
                  <div className={`banner ${consentGranted ? "success" : "warning"} mt-2`}>
                    <div className="flex items-center justify-between gap-2">
                      <span>
                        {consentGranted
                          ? "Consent is recorded. Audio capture is available; transcription uses Whisper in live mode."
                          : "Consent for consultation capture has not been recorded. Audio capture is blocked until it is."}
                      </span>
                      <div className="button-row">
                        {!consentGranted ? (
                          <button className="btn btn-sm" onClick={() => recordConsent.mutate()} disabled={recordConsent.isPending}>
                            {recordConsent.isPending ? "Recording consent…" : "Record consent"}
                          </button>
                        ) : recording ? (
                          <button className="btn btn-danger btn-sm" onClick={stopRecording}>Stop & transcribe</button>
                        ) : (
                          <button className="btn btn-sm" onClick={startRecording} disabled={transcribing}>
                            {transcribing ? <><span className="spinner" /> Transcribing…</> : "Record audio"}
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ) : null}
                <div className="button-row mt-2">
                  <button className="btn btn-primary" onClick={() => generate.mutate()} disabled={generate.isPending || transcript.trim().length < 10}>
                    {generate.isPending ? <><span className="spinner" /> Generating draft…</> : "Generate draft"}
                  </button>
                  <button className="btn" onClick={() => setTranscript(tab.transcript)}>Load seeded transcript</button>
                  <span className="small muted">Paste text in the demo; audio upload uses Whisper in production.</span>
                </div>
                {tab.feature === "F1" || tab.feature === "F2" ? (
                  <div className="banner mt-3">
                    Consent and allergy verification are captured separately below the draft. The model cannot mark either as complete.
                  </div>
                ) : null}
              </>
            ) : null}

            {tab.kind === "icu" ? (
              <>
                <div className="banner mb-3">
                  Source: device feed for the seeded ICU encounter (18–19 Oct). {icu.data?.entries.length ?? 0} structured readings available.
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
              </>
            ) : null}

            {tab.kind === "referral" ? (
              <>
                <div className="flex items-center justify-between mb-2">
                  <div className="card-sub">Referral queue · {referrals.data?.referrals.length ?? 0}</div>
                  <button className="btn btn-primary btn-sm" onClick={() => generate.mutate()} disabled={generate.isPending}>
                    {generate.isPending ? <><span className="spinner" /> Drafting…</> : "Draft nephrology referral"}
                  </button>
                </div>
                <div className="stack">
                  {referrals.data?.referrals.map((referral) => (
                    <div key={referral.id} className="list-card">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="strong">{referral.specialty}</div>
                          <div className="small muted">{referral.specialist || "Specialist service"} · {referral.urgency}</div>
                        </div>
                        <span className={`badge ${referral.status === "completed" ? "badge-success" : referral.status === "acknowledged" ? "badge-ai" : "badge-warning"}`}>{referral.status}</span>
                      </div>
                      <div className="small mt-2">{referral.question}</div>
                      <div className="button-row mt-2">
                        {referral.status === "sent" ? (
                          <button className="btn btn-sm" onClick={() => acknowledgeReferral.mutate(referral.id)} disabled={acknowledgeReferral.isPending}>Mark acknowledged</button>
                        ) : null}
                        {referral.status === "acknowledged" ? (
                          <button className="btn btn-sm" onClick={() => {
                            const summary = window.prompt("Specialist response summary (demo)");
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
                </div>
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
              <div>{hasDraft ? "Generate one from the input panel. The draft will appear here with evidence attached." : "Laboratory review is kept as a support view; F11 is the referral workflow."}</div>
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
