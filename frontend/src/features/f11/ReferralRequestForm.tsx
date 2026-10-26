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
    <div className="referral-form">
      <div className="form-grid">
        <label className="form-field">
          <span className="field-label">Specialty</span>
          <input className="input" value={specialty} placeholder="Nephrology" onChange={(event) => setSpecialty(event.target.value)} />
        </label>
        <label className="form-field">
          <span className="field-label">Urgency</span>
          <select className="select" value={urgency} onChange={(event) => setUrgency(event.target.value)}>
            <option value="">Not set (routine)</option>
            <option value="routine">Routine</option>
            <option value="urgent">Urgent</option>
            <option value="emergency">Emergency</option>
          </select>
        </label>
        <label className="form-field form-span">
          <span className="field-label">Question to the specialist</span>
          <input className="input" value={question} onChange={(event) => setQuestion(event.target.value)} />
        </label>
      </div>
      <div className="field-hint">
        Leave the specialty blank to use an abnormal kidney result. Leave the question blank and write it in the draft; approval is refused until it is written.
      </div>
      <div className="button-row mt-3">
        <button className="btn btn-primary" onClick={() => draft.mutate()} disabled={!allowed || draft.isPending} aria-busy={draft.isPending || undefined}>
          {draft.isPending ? <><span className="spinner" /> Drafting…</> : "Draft referral"}
        </button>
        {!allowed ? <span className="small muted">Your role cannot draft a referral.</span> : null}
      </div>
      {error ? <div className="error-box mt-2">{error}</div> : null}
    </div>
  );
}
