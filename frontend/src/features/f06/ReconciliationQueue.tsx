import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../../api";
import { EvidenceChip } from "../../components/Evidence";
import { useCan } from "../../session";
import { DECISION_LABEL, decisionText, noteOk } from "./rules";
import { MIN_NOTE } from "./types";
import type { Decision, Discrepancy, ProposedOrderChange, ReconciliationResult } from "./types";

type Resolved = { proposed_order_change: ProposedOrderChange | null };

function DecisionForm({ item, onDone }: { item: Discrepancy; onDone: (change: ProposedOrderChange | null) => void }) {
  const queryClient = useQueryClient();
  const [decision, setDecision] = useState<Decision>("continue");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const resolve = useMutation({
    mutationFn: () => post<Resolved>(`/medications/reconciliation/${item.id}/resolve`, { decision, note: note.trim() }),
    onSuccess: (result) => {
      setError("");
      setNote("");
      queryClient.invalidateQueries({ queryKey: ["reconciliation"] });
      queryClient.invalidateQueries({ queryKey: ["timeline"] });
      onDone(result.proposed_order_change);
    },
    onError: (err: any) => setError(String(err?.message || err)),
  });
  return (
    <div className="mt-2">
      <div className="form-row" style={{ alignItems: "flex-end" }}>
        <div>
          <label className="field-label">Decision</label>
          <select className="input" value={decision} onChange={(event) => setDecision(event.target.value as Decision)}>
            {(Object.keys(DECISION_LABEL) as Decision[]).map((key) => (
              <option key={key} value={key}>{DECISION_LABEL[key]}</option>
            ))}
          </select>
        </div>
        <div style={{ flex: 1, minWidth: 240 }}>
          <label className="field-label">Why</label>
          <input
            className="input"
            value={note}
            placeholder={`At least ${MIN_NOTE} characters`}
            onChange={(event) => setNote(event.target.value)}
          />
        </div>
        <button className="btn btn-sm btn-primary" disabled={!noteOk(note) || resolve.isPending} onClick={() => resolve.mutate()}>
          Record decision
        </button>
      </div>
      {error ? <div className="error-box mt-2">{error}</div> : null}
    </div>
  );
}

export default function ReconciliationQueue() {
  const canResolve = useCan("resolve_discrepancy");
  const [proposed, setProposed] = useState<ProposedOrderChange | null>(null);
  const recon = useQuery<ReconciliationResult>({
    queryKey: ["reconciliation"],
    queryFn: () => get("/medications/reconciliation"),
  });
  const items = recon.data?.discrepancies ?? [];

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">Differences to decide</div>
        <span className={`badge ${recon.data?.unresolved_count ? "badge-warning" : "badge-success"}`}>
          {recon.data?.unresolved_count ?? 0} open
        </span>
      </div>
      <div className="card-pad">
        <div className="small muted mb-2">
          A decision is a record of what a clinician decided. It does not order, stop or change any medicine.
        </div>
        {recon.isLoading ? <div className="loading">Loading…</div> : null}
        {!recon.isLoading && !items.length ? <div className="empty">No differences found.</div> : null}
        {proposed ? (
          <div className="alert-card mb-2">
            <div className="alert-title">
              Proposed: {proposed.action} {proposed.drug}
            </div>
            <div className="small muted">{proposed.message}</div>
            <button className="btn btn-sm btn-ghost mt-1" onClick={() => setProposed(null)}>Dismiss</button>
          </div>
        ) : null}
        {items.map((item) => (
          <div className="alert-card mb-2" key={item.id}>
            <div className="flex items-center gap-2">
              <span className={`badge ${item.status === "resolved" ? "badge-success" : "badge-warning"}`}>{item.status}</span>
              <span className="badge badge-neutral">{item.kind}</span>
              <strong className="fs-13">{item.home_med}</strong>
              <span className="small muted">→ {item.current_order || "not ordered"}</span>
            </div>
            <div className="alert-explanation">{item.explanation}</div>
            {item.field ? (
              <div className="small muted">
                {item.field}: home “{item.home_value || "—"}” → inpatient “{item.current_value || "—"}”
              </div>
            ) : null}
            <div className="flex items-center gap-2 flex-wrap">
              {item.evidence_event_ids.map((id) => <EvidenceChip key={id} eventIds={[id]} label="evidence" />)}
            </div>
            {item.status === "resolved" ? (
              <div className="small mt-1">
                {decisionText(item.decision)} by {item.decided_by}: {item.note}
              </div>
            ) : (
              <>
                {item.earlier_decision ? (
                  <div className="small muted mt-1">
                    Earlier decision ({decisionText(item.earlier_decision.decision)} by {item.earlier_decision.decided_by}) no longer applies: the record changed.
                  </div>
                ) : null}
                <div className="alert-action">{item.recommended_action}</div>
                {canResolve ? <DecisionForm item={item} onDone={setProposed} /> : null}
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
