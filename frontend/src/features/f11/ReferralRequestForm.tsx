import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../../api";
import { useCan } from "../../session";
import { referralBody } from "./rules";

/** Ask for a referral draft: specialty, urgency and the question. The draft is then reviewed and edited as usual. */
export default function ReferralRequestForm() {
  const allowed = useCan("clinical_draft");
  const queryClient = useQueryClient();
  const [specialty, setSpecialty] = useState("");
  const [urgency, setUrgency] = useState("");
  const [question, setQuestion] = useState("");
  const [error, setError] = useState("");

  const draft = useMutation({
    mutationFn: () => post<any>("/referrals/generate", referralBody(specialty, urgency, question)),
    onSuccess: () => {
      setError("");
      queryClient.invalidateQueries();
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });

  return (
    <div className="mb-3">
      <div className="form-row">
        <div>
          <label className="field-label">Specialty</label>
          <input className="input" value={specialty} placeholder="Nephrology" onChange={(event) => setSpecialty(event.target.value)} />
        </div>
        <div>
          <label className="field-label">Urgency</label>
          <select className="input" value={urgency} onChange={(event) => setUrgency(event.target.value)}>
            <option value="">Not set (routine)</option>
            <option value="routine">Routine</option>
            <option value="urgent">Urgent</option>
            <option value="emergency">Emergency</option>
          </select>
        </div>
        <div style={{ flex: 1, minWidth: 240 }}>
          <label className="field-label">Question to the specialist</label>
          <input className="input" value={question} onChange={(event) => setQuestion(event.target.value)} />
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => draft.mutate()} disabled={!allowed || draft.isPending}>
          {draft.isPending ? <><span className="spinner" /> Drafting…</> : "Draft referral"}
        </button>
      </div>
      <div className="small muted mt-1">
        Leave the specialty blank to use an abnormal kidney result. Leave the question blank and write it in the draft; approval is refused until it is written.
      </div>
      {!allowed ? <div className="small muted mt-1">Your role cannot draft a referral.</div> : null}
      {error ? <div className="error-box mt-2">{error}</div> : null}
    </div>
  );
}
