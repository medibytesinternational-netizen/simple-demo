import { EvidenceChip } from "../../components/Evidence";
import type { ClaimPrep } from "../../types";
import { tpaLabel, type F12TpaReview } from "./types";

/** Where the TPA review stands: ready for a human, or blocked by contradictions. */
export function TpaState({ claim }: { claim?: ClaimPrep }) {
  const tpa = claim?.tpa_review as F12TpaReview | undefined;
  const blocked = tpa?.status === "needs_clarification";
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">TPA review state</div>
          <div className="card-sub">Nothing is sent to the payer from here</div>
        </div>
        <span className={`badge ${blocked ? "badge-critical" : "badge-success"}`}>{tpaLabel(tpa?.status)}</span>
      </div>
      <div className="card-pad">
        <div className="check-row">
          <span style={{ flex: 1 }}>Pack status</span>
          <span className="badge badge-neutral">{tpaLabel(claim?.status)}</span>
        </div>
        <div className="check-row">
          <span style={{ flex: 1 }}>Open contradictions</span>
          <span className="mono small">{tpa?.contradiction_count ?? "—"}</span>
        </div>
        <div className="check-row">
          <span style={{ flex: 1 }}>Missing documents</span>
          <span className="mono small">{claim?.missing_documents.length ?? "—"}</span>
        </div>
        {tpa?.evidence_event_ids?.length ? (
          <div className="mt-1">
            <EvidenceChip eventIds={tpa.evidence_event_ids} label="TPA evidence" />
          </div>
        ) : null}
      </div>
    </div>
  );
}
