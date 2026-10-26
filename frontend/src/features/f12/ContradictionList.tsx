import { EvidenceChip } from "../../components/Evidence";
import { Banner, ListRow, Pill } from "../../components/ui";
import type { F12Contradiction } from "./types";

/** Contradictions found before submission, each with a link to both sources and what they say. */
export function ContradictionList({ items }: { items: F12Contradiction[] }) {
  if (!items.length) {
    return <Banner tone="success">No contradictions detected. TPA review can proceed to human review.</Banner>;
  }
  return (
    <div className="contradictions">
      <div className="rows">
        {items.map((item) => (
          <ListRow
            key={item.id}
            icon="alert"
            tone="critical"
            title={item.title}
            chips={<Pill tone="critical">{item.kind.replaceAll("_", " ")}</Pill>}
            body={item.explanation}
            expand={
              item.evidence?.length ? (
                <div className="contradiction-sources">
                  {item.evidence.map((source) => (
                    <div className="contradiction-source" key={source.event_id}>
                      <EvidenceChip eventIds={[source.event_id]} label={source.title} />
                      {source.quote ? <q className="small muted">{source.quote}</q> : null}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="contradiction-sources">
                  <EvidenceChip eventIds={item.evidence_event_ids} />
                </div>
              )
            }
          />
        ))}
      </div>
      <Banner tone="warning">
        TPA review is blocked. A human must resolve every contradiction before this pack is review-ready.
      </Banner>
    </div>
  );
}
