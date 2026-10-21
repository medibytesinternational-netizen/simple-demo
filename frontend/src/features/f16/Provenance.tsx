import type { Provenance } from "./types";

type Facts = Provenance & { occurred_at: string; source: string; author_name: string };

/** Who, when and from which source, for any event. Used by the timeline and the evidence drawer. */
export function ProvenanceFacts({ event }: { event: Facts }) {
  return (
    <div className="timeline-meta" data-testid="provenance">
      <span className={`badge ${event.ai_drafted ? "badge-ai" : "badge-neutral"}`}>
        {event.ai_drafted ? "AI-drafted" : "Human-recorded"}
      </span>
      <span>{event.authorship}</span>
      <span>{new Date(event.occurred_at).toLocaleString()}</span>
      <span title={event.source}>from {event.source_label}</span>
    </div>
  );
}
