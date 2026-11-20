import { EvidenceChip } from "../../components/Evidence";
import { ListRow, Pill } from "../../components/ui";
import type { F12Contradiction } from "./types";

/** Contradictions found before submission, each with a link to both sources and what they say. */
export function ContradictionList({ items }: { items: F12Contradiction[] }) {
  return (
    <>
      {items.map((item) => (
        <ListRow
          key={item.id}
          icon="alert"
          tone="critical"
          title={item.title}
          chips={<Pill tone="critical">Contradiction · {item.kind.replaceAll("_", " ")}</Pill>}
          body={item.explanation}
          expand={
            <details className="rev-why">
              <summary>Sources ({item.evidence?.length || item.evidence_event_ids.length})</summary>
              <div className="contradiction-sources">
                {item.evidence?.length ? item.evidence.map((source) => (
                  <div className="contradiction-source" key={source.event_id}>
                    <EvidenceChip eventIds={[source.event_id]} label={source.title} />
                    {source.quote ? <q className="small muted">{source.quote}</q> : null}
                  </div>
                )) : <EvidenceChip eventIds={item.evidence_event_ids} />}
              </div>
            </details>
          }
        />
      ))}
    </>
  );
}
