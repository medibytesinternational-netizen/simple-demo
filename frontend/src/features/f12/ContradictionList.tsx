import { EvidenceChip } from "../../components/Evidence";
import type { F12Contradiction } from "./types";

/** Contradictions found before submission, each with a link to both sources and what they say. */
export function ContradictionList({ items }: { items: F12Contradiction[] }) {
  if (!items.length) {
    return <div className="small muted">No contradictions detected. TPA review can proceed to human review.</div>;
  }
  return (
    <>
      {items.map((item) => (
        <div className="alert-card critical mb-2" key={item.id}>
          <div className="flex items-center gap-2">
            <span className="badge badge-critical">{item.kind.replaceAll("_", " ")}</span>
            <strong className="fs-13">{item.title}</strong>
          </div>
          <div className="alert-explanation">{item.explanation}</div>
          {item.evidence?.length ? (
            <div className="mt-1">
              {item.evidence.map((source) => (
                <div className="small muted" key={source.event_id}>
                  <EvidenceChip eventIds={[source.event_id]} label={source.title} />
                  {source.quote ? <> “{source.quote}”</> : null}
                </div>
              ))}
            </div>
          ) : (
            <EvidenceChip eventIds={item.evidence_event_ids} />
          )}
        </div>
      ))}
      <div className="banner warning">
        TPA review is blocked. A human must resolve every contradiction before this pack is review-ready.
      </div>
    </>
  );
}
