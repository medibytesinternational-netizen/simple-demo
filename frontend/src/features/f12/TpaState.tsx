import { EvidenceChip } from "../../components/Evidence";
import { Panel, Pill } from "../../components/ui";
import type { ClaimPrep } from "../../types";
import { tpaLabel, type F12TpaReview } from "./types";

/** Where the TPA review stands: ready for a human, or blocked by contradictions. */
export function TpaState({ claim }: { claim?: ClaimPrep }) {
  const tpa = claim?.tpa_review as F12TpaReview | undefined;
  const blocked = tpa?.status === "needs_clarification";
  return (
    <Panel
      title="TPA review state"
      sub="Nothing is sent to the payer from here"
      actions={<Pill tone={blocked ? "critical" : "success"} dot>{tpaLabel(tpa?.status)}</Pill>}
      padded
    >
      <div className="checklist">
        <div className="check-row">
          <span className="check-label">Pack status</span>
          <Pill>{tpaLabel(claim?.status)}</Pill>
        </div>
        <div className="check-row">
          <span className="check-label">Open contradictions</span>
          <span className="mono small">{tpa?.contradiction_count ?? "unknown"}</span>
        </div>
        <div className="check-row">
          <span className="check-label">Missing documents</span>
          <span className="mono small">{claim?.missing_documents.length ?? "unknown"}</span>
        </div>
      </div>
      {tpa?.evidence_event_ids?.length ? (
        <div className="mt-2">
          <EvidenceChip eventIds={tpa.evidence_event_ids} label="TPA evidence" />
        </div>
      ) : null}
    </Panel>
  );
}
