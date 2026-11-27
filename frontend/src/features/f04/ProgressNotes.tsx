import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { generateVoiceDraft, get, openStoredFile, post } from "../../api";
import { Link } from "react-router-dom";
import { VoiceInput } from "../../components/VoiceInput";
import { DraftReview } from "../../components/DraftReview";
import { currentRole } from "../../components/roles";
import type { Draft } from "../../types";

type Order = { study: string; request_type: string; request_id: string; priority: string };
type Row = { event_id: string; time: string; notes: string; signed_by: string; signed_role: string; orders?: Order[] };
type Table = { entries: Row[]; can_write: string[] };

const when = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
};

/** Daily progress notes: doctors and nurses dictate entries into one table, signed in their name. */
export function ProgressNotes() {
  const queryClient = useQueryClient();
  const table = useQuery({ queryKey: ["progress-notes"], queryFn: () => get<Table>("/progress-notes") });
  const meta = useQuery<{ patient: { id: string }; encounter: { id: string } }>({ queryKey: ["meta"], queryFn: () => get("/meta") });
  const consents = useQuery<{ consents: Array<{ granted: boolean; consent_type: string }> }>({
    queryKey: ["consents", "progress", meta.data?.patient.id, meta.data?.encounter.id],
    queryFn: () => get(`/patients/${meta.data!.patient.id}/consents?encounter_id=${encodeURIComponent(meta.data!.encounter.id)}`),
    enabled: Boolean(meta.data?.patient.id && meta.data?.encounter.id),
  });
  const consentGranted = Boolean(consents.data?.consents?.some((item) => item.granted && ["consultation_capture", "audio_recording"].includes(item.consent_type)));
  const canRecordConsent = currentRole() === "admin";
  const rows = table.data?.entries || [];
  const canWrite = !table.isSuccess || table.data.can_write.length > 0;
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);

  const recordConsent = useMutation({
    mutationFn: () => post(`/patients/${meta.data!.patient.id}/consents?encounter_id=${encodeURIComponent(meta.data!.encounter.id)}`, {
      consent_type: "consultation_capture", granted: true, note: "Patient agrees to progress-note audio capture.",
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["consents", "progress"] }),
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const capture = async (audio: Blob, filename: string | undefined) => {
    setSaved("");
    const made = await generateVoiceDraft(audio, filename || "progress.webm", "F4");
    await queryClient.invalidateQueries();
    setDraft(made);
    setSaved("Progress note draft is ready for review.");
  };

  const report = useMutation({
    mutationFn: () => post<{ document_id: string }>("/progress-notes/report"),
    onSuccess: async (made) => {
      setError("");
      queryClient.invalidateQueries({ queryKey: ["timeline"] });
      try {
        await openStoredFile(made.document_id);
      } catch (err: any) {
        setError(String(err?.message || err));
      }
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  return (
    <div className="progress-notes">
      <div className="card">
        <div className="card-header"><h2>Add today's progress note</h2></div>
        <div className="card-body">
          {canWrite ? (
            <>
              <span className="small muted">Record or upload the dictation. Review the progress note draft before it is signed and added below.</span>
              {!consentGranted ? (
                <div className="banner warning mt-2">
                  <span>{canRecordConsent ? "Record patient consent before capturing progress-note audio." : "A doctor must record patient consent before progress-note audio is available."}</span>
                  {canRecordConsent ? <button className="btn btn-sm btn-primary ml-2" onClick={() => recordConsent.mutate()} disabled={!meta.data || recordConsent.isPending}>
                    {recordConsent.isPending ? "Saving…" : "Record consent"}
                  </button> : null}
                </div>
              ) : null}
              <VoiceInput consentGranted={consentGranted} disabled={!consentGranted} feature="F4" capture={capture} />
              {saved ? <span className="small" role="status">{saved}</span> : null}
            </>
          ) : (
            <span className="small muted">Your role cannot write progress notes.</span>
          )}
        </div>
      </div>
      {draft ? <DraftReview draft={draft} /> : null}
      <div className="card">
        <div className="card-header">
          <h2>Progress notes</h2>
          <button type="button" className="btn btn-sm" disabled={!rows.length || report.isPending}
            aria-busy={report.isPending || undefined} onClick={() => report.mutate()}>
            {report.isPending ? <><span className="spinner" /> Generating...</> : "Generate report"}
          </button>
        </div>
        {error ? <div className="error-box" role="alert">{error}</div> : null}
        <div className="table-wrap">
          <table className="table progress-table">
            <thead><tr><th>Date and time</th><th>Notes</th><th>Name and sign</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.event_id}>
                  <td>{when(r.time)}</td>
                  <td>
                    <div style={{ whiteSpace: "pre-line" }}>{r.notes}</div>
                    {r.orders?.length ? (
                      <div className="pn-orders" aria-label="Requests raised from this note">
                        {r.orders.map((o) => (
                          <Link key={o.request_id} className={`pn-order ${o.priority === "urgent" ? "pn-order--urgent" : ""}`}
                            to="/documents?tab=requisition">
                            {o.request_type === "imaging" ? "Radiology" : "Investigation"}: {o.study} → Requested{o.priority === "urgent" ? " · URGENT" : ""}
                          </Link>
                        ))}
                      </div>
                    ) : null}
                  </td>
                  <td>{r.signed_by}<div className="small muted">{r.signed_role}</div></td>
                </tr>
              ))}
              {!rows.length ? (
                <tr><td colSpan={3} className="muted small">{table.isLoading ? "Loading..." : "No entries yet."}</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
