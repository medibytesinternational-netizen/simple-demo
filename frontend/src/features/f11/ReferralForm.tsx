import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, get, openStoredFile, patch, post } from "../../api";
import { VoiceInput } from "../../components/VoiceInput";
import { currentRole } from "../../components/roles";
import type { Draft } from "../../types";
import { referralStatusLabel } from "./rules";

const TYPES: [string, string][] = [
  ["immediate", "Immediate (within one hour)"],
  ["urgent", "Urgent (within four hours)"],
  ["routine", "Routine (within twenty-four hours)"],
];
const HEADER: [string, string][] = [["name", "Name"], ["sex", "Sex"], ["ward", "Ward"], ["hid", "HID number"]];

const textOf = (v: any) => String(v && typeof v === "object" ? v.text ?? "" : v ?? "").trim();
const authored = (text: string) => ({ text, source_event_ids: [], source_segment_ids: [], confidence: 1, human_authored: true });
const when = (iso?: string) => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
};

/** Dictate a referral, check the filled form (part one), approve it to sign and store it on the timeline. */
async function dictate(audio: Blob, filename?: string): Promise<Draft> {
  const form = new FormData();
  form.append("file", audio, filename || "referral.webm");
  const receipt = await api<{ audio_id: string }>("/referrals/record", { method: "POST", body: form });
  const deadline = Date.now() + 5 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    const status = await api<{ status: string; error?: string; draft?: Draft }>(`/referrals/record/${encodeURIComponent(receipt.audio_id)}`);
    if (status.status === "succeeded" && status.draft) return status.draft;
    if (status.status === "failed") throw new Error(status.error || "The recording could not be processed");
  }
  throw new Error("The pipeline is taking too long. Try again in a minute.");
}

export function ReferralForm() {
  const queryClient = useQueryClient();
  // Known from the signed-in role straight away, so the voice box never flashes away while loading.
  const canRefer = ["admin", "senior"].includes(currentRole());
  const latest = useQuery({ queryKey: ["referral-form"], queryFn: () => get<{ draft: Draft | null }>("/referrals/form"), enabled: canRefer });
  const referrals = useQuery({ queryKey: ["referrals"], queryFn: () => get<{ referrals: any[] }>("/referrals") });
  const draft = latest.data?.draft || null;
  const pending = draft && draft.status !== "approved" && draft.status !== "rejected" ? draft : null;

  return (
    <div className="progress-notes">
      {canRefer ? (
        pending ? (
          <FormReview draft={pending} />
        ) : (
          <div className="card">
            <div className="card-header"><h2>New referral</h2></div>
            <div className="card-body">
              <span className="small muted">
                Record or upload your referral. The form is filled from what you say and from the patient's earlier record; you check it and approve.
              </span>
              <VoiceInput consentGranted feature="F11" capture={async (audio, filename) => {
                await dictate(audio, filename);
                await queryClient.invalidateQueries({ queryKey: ["referral-form"] });
              }} />
              {draft?.status === "approved" ? (
                <span className="small" role="status">Last referral approved and stored on the timeline.</span>
              ) : null}
            </div>
          </div>
        )
      ) : (
        <div className="card"><div className="card-body"><span className="small muted">Referrals are made by senior doctors.</span></div></div>
      )}

      <div className="card">
        <div className="card-header"><h2>Referrals</h2></div>
        <div className="table-wrap">
          <table className="table progress-table">
            <thead><tr><th>Date and time</th><th>Department / unit chief</th><th>Type</th><th>Status</th></tr></thead>
            <tbody>
              {(referrals.data?.referrals || []).map((r) => (
                <tr key={r.id}>
                  <td>{when(r.created_at)}</td>
                  <td>{r.specialty}{r.specialist ? <div className="small muted">{r.specialist}</div> : null}</td>
                  <td>{r.urgency === "emergency" ? "Immediate" : r.urgency === "urgent" ? "Urgent" : "Routine"}</td>
                  <td>{referralStatusLabel(r.status)}</td>
                </tr>
              ))}
              {!referrals.data?.referrals?.length ? <tr><td colSpan={4} className="muted small">No referrals yet.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function FormReview({ draft }: { draft: Draft }) {
  const queryClient = useQueryClient();
  const c = draft.content || {};
  const initial = {
    referral_type: c.referral_type || "",
    unit_chief: textOf(c.unit_chief),
    department: textOf(c.department),
    details: (c.salient_details || []).map(textOf).filter(Boolean).join("\n"),
  };
  const [v, setV] = useState(initial);
  const [error, setError] = useState("");
  useEffect(() => setV(initial), [draft.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const recordItems = new Set((c.salient_details || []).filter((d: any) => d?.origin === "record").map(textOf));
  const changed = JSON.stringify(v) !== JSON.stringify(initial);

  const save = async () => {
    if (!changed) return;
    const old: any[] = c.salient_details || [];
    await patch(`/referrals/form/${draft.id}`, { content: {
      referral_type: v.referral_type || null,
      unit_chief: v.unit_chief === initial.unit_chief ? c.unit_chief : v.unit_chief.trim() ? authored(v.unit_chief.trim()) : null,
      department: v.department === initial.department ? c.department : v.department.trim() ? authored(v.department.trim()) : null,
      salient_details: v.details.split("\n").map((t) => t.trim()).filter(Boolean).map((t) => old.find((d) => textOf(d) === t) || authored(t)),
    } });
  };

  const approve = useMutation({
    mutationFn: async () => {
      await save();
      return post<{ document_id: string }>(`/referrals/form/${draft.id}/approve`);
    },
    onSuccess: async (done) => {
      setError("");
      await queryClient.invalidateQueries();
      if (done.document_id) openStoredFile(done.document_id).catch(() => undefined);
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  const discard = useMutation({
    mutationFn: () => post(`/referrals/form/${draft.id}/discard`),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (err: any) => setError(String(err?.message || err)),
  });

  const head = c.header || {};
  return (
    <div className="card">
      <div className="card-header"><h2>Referral form: part one</h2><span className="small muted">Check, edit if needed, then approve</span></div>
      {error ? <div className="error-box" role="alert">{error}</div> : null}
      <div className="referral-head">
        {HEADER.map(([k, label]) => <div key={k}><span>{label}</span><b>{head[k] || "-"}</b></div>)}
      </div>
      <div className="opd-editor">
        <fieldset className="referral-types">
          <legend>Referral type</legend>
          {TYPES.map(([key, label]) => (
            <label key={key}>
              <input type="radio" name="referral_type" checked={v.referral_type === key} onChange={() => setV({ ...v, referral_type: key })} /> {label}
            </label>
          ))}
        </fieldset>
        <label>Unit chief requested of (doctor's name)
          <input className="input" value={v.unit_chief} onChange={(e) => setV({ ...v, unit_chief: e.target.value })} />
        </label>
        <label>Department
          <input className="input" value={v.department} onChange={(e) => setV({ ...v, department: e.target.value })} />
        </label>
        <label>Salient details of the patient or reason for referral <span className="hint">One per line</span>
          <textarea className="textarea" rows={6} value={v.details} onChange={(e) => setV({ ...v, details: e.target.value })} />
        </label>
        {recordItems.size ? <span className="small muted">Lines taken from the patient's earlier record: {[...recordItems].length}. Edit or remove them as needed.</span> : null}
        <span className="small muted">Doctor's name and signature, date and time are added when you approve.</span>
        <div className="button-row">
          <button className="btn" onClick={() => discard.mutate()} disabled={approve.isPending || discard.isPending}>Discard</button>
          <button className="btn btn-primary btn-sm" onClick={() => approve.mutate()} disabled={approve.isPending} aria-busy={approve.isPending || undefined}>
            {approve.isPending ? <><span className="spinner" /> Approving...</> : "Approve and save to timeline"}
          </button>
        </div>
      </div>
    </div>
  );
}
