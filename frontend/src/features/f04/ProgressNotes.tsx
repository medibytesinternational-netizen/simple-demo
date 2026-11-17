import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, openStoredFile, post, recordProgressNote } from "../../api";
import { Link } from "react-router-dom";
import { VoiceInput } from "../../components/VoiceInput";

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
  const rows = table.data?.entries || [];
  const canWrite = !table.isSuccess || table.data.can_write.length > 0;
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");

  const capture = async (audio: Blob, filename: string | undefined) => {
    setSaved("");
    await recordProgressNote(audio, filename || "progress.webm");
    await queryClient.invalidateQueries();
    setSaved("Added to the progress notes and the timeline.");
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
              <span className="small muted">Record or upload the dictation. It is written up, signed in your name and added below.</span>
              <VoiceInput consentGranted feature="F4" capture={capture} />
              {saved ? <span className="small" role="status">{saved}</span> : null}
            </>
          ) : (
            <span className="small muted">Your role cannot write progress notes.</span>
          )}
        </div>
      </div>
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
