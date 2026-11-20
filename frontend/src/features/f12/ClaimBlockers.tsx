import { Link } from "react-router-dom";
import { EvidenceChip } from "../../components/Evidence";
import { Banner, ListRow, Panel, Pill, Skeleton } from "../../components/ui";
import type { ClaimPrep } from "../../types";
import { inr } from "../f13/leakage";
import { ContradictionList } from "./ContradictionList";
import { RESOLVE_DOCUMENT } from "./status";
import type { F12Contradiction } from "./types";

/**
 * Everything that keeps the pack from being review-ready, in one list: missing
 * documents, contradictions and bill lines with no documentation (claims.py status rule).
 */
export function ClaimBlockers({ claim, loading }: { claim?: ClaimPrep; loading: boolean }) {
  const missing = claim?.missing_documents || [];
  const contradictions = (claim?.contradictions || []) as F12Contradiction[];
  const unsupported = claim?.unsupported_items || [];
  const total = missing.length + contradictions.length + unsupported.length;

  if (loading) return <Panel title="Blockers before review" padded><Skeleton count={3} /></Panel>;
  if (!claim) return null;
  if (!total) {
    return (
      <Banner tone="success" title="No blockers">
        All required documents are present, there are no contradictions and every bill line is documented. The pack is ready for human review; nothing is submitted.
      </Banner>
    );
  }
  return (
    <Panel
      className="rev-blockers"
      title="Blockers before review"
      count={total}
      sub={claim.discharge_signed
        ? "A human must resolve each item. The app cannot create a payer document."
        : "Signing the discharge summary clears its gap. A human must resolve the rest; the app cannot create a payer document."}
    >
      <div className="rows rows-flush">
        {missing.map((doc) => {
          const fix = RESOLVE_DOCUMENT[doc.key];
          return (
            <ListRow
              key={doc.key}
              icon="folder"
              tone="critical"
              title={doc.label}
              chips={<Pill tone="critical">Missing document</Pill>}
              side={fix ? <Link className="btn btn-sm" to={fix.to}>{fix.label}</Link> : null}
            />
          );
        })}
        <ContradictionList items={contradictions} />
        {unsupported.map((item) => (
          <ListRow
            key={item.id}
            icon="billing"
            tone="critical"
            title={item.description}
            meta={<span className="mono">{item.code} · {inr(item.amount)}</span>}
            chips={
              <>
                <Pill tone="critical">Billed without documentation</Pill>
                {item.evidence_event_ids?.length ? <EvidenceChip eventIds={item.evidence_event_ids} label="billing source" /> : null}
              </>
            }
          />
        ))}
      </div>
    </Panel>
  );
}
