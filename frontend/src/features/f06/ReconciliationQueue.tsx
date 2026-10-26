import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../../api";
import { EvidenceChip } from "../../components/Evidence";
import { Icon } from "../../components/icons";
import { Banner, EmptyState, ListRow, Panel, Pill, Skeleton } from "../../components/ui";
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
    <div className="decision-form">
      <div className="form-row">
        <div className="form-field">
          <label className="field-label">Decision</label>
          <select className="input" value={decision} onChange={(event) => setDecision(event.target.value as Decision)}>
            {(Object.keys(DECISION_LABEL) as Decision[]).map((key) => (
              <option key={key} value={key}>{DECISION_LABEL[key]}</option>
            ))}
          </select>
        </div>
        <div className="form-field decision-why">
          <label className="field-label">Why</label>
          <input
            className="input"
            value={note}
            placeholder={`At least ${MIN_NOTE} characters`}
            onChange={(event) => setNote(event.target.value)}
          />
        </div>
        <button
          className="btn btn-sm btn-primary"
          disabled={!noteOk(note) || resolve.isPending}
          onClick={() => resolve.mutate()}
          aria-busy={resolve.isPending || undefined}
        >
          {resolve.isPending ? <span className="spinner" /> : null}
          Record decision
        </button>
      </div>
      {error ? <div className="error-box mt-2" role="alert">{error}</div> : null}
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
    <Panel
      title="Decide differences"
      sub="A decision is a record of what a clinician decided. It does not order, stop or change any medicine."
      actions={(
        <Pill tone={recon.data?.unresolved_count ? "warning" : "success"} dot>
          {recon.data?.unresolved_count ?? 0} open
        </Pill>
      )}
    >
      {proposed ? (
        <div className="panel-body">
          <Banner
            tone="info"
            title={`Proposed: ${proposed.action} ${proposed.drug}`}
            actions={<button className="btn btn-sm btn-ghost" onClick={() => setProposed(null)}>Dismiss</button>}
          >
            {proposed.message}
          </Banner>
        </div>
      ) : null}
      {recon.isLoading ? <div className="panel-body"><Skeleton variant="rows" count={2} /></div> : null}
      {!recon.isLoading && !items.length ? (
        <EmptyState icon="check" title="No differences found.">
          The home list matches the current orders. New differences appear here when an order changes.
        </EmptyState>
      ) : null}
      {items.length ? (
        <div className="rows rows-flush">
          {items.map((item) => (
            <ListRow
              key={item.id}
              icon="pill"
              tone={item.status === "resolved" ? "success" : "warning"}
              muted={item.status === "resolved"}
              title={(
                <>
                  {item.home_med}
                  <span className="recon-arrow"> → </span>
                  <span className="recon-current">{item.current_order || "not ordered"}</span>
                </>
              )}
              meta={item.field ? (
                <>{item.field}: home “{item.home_value || "none"}”, inpatient “{item.current_value || "none"}”</>
              ) : undefined}
              body={item.explanation}
              chips={(
                <>
                  <Pill tone={item.status === "resolved" ? "success" : "warning"}>{item.status}</Pill>
                  <Pill>{item.kind}</Pill>
                  {item.evidence_event_ids.map((id) => <EvidenceChip key={id} eventIds={[id]} label="evidence" />)}
                </>
              )}
              expand={item.status === "resolved" ? (
                <div className="recon-decided">
                  <Icon name="check" size={14} />
                  <span>{decisionText(item.decision)} by {item.decided_by}: {item.note}</span>
                </div>
              ) : (
                <div className="recon-open">
                  {item.earlier_decision ? (
                    <div className="small muted">
                      Earlier decision ({decisionText(item.earlier_decision.decision)} by {item.earlier_decision.decided_by}) no longer applies: the record changed.
                    </div>
                  ) : null}
                  <div className="alert-action">{item.recommended_action}</div>
                  {canResolve ? <DecisionForm item={item} onDone={setProposed} /> : null}
                </div>
              )}
            />
          ))}
        </div>
      ) : null}
    </Panel>
  );
}
