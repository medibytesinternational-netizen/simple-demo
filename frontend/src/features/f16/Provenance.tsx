import type { Provenance } from "./types";
import { Pill } from "../../components/ui";

type Facts = Provenance & { occurred_at: string; source: string; author_name: string };

/** Who, when and from which source, for any event. Used by the timeline and the evidence drawer. */
export function ProvenanceFacts({ event }: { event: Facts }) {
  return (
    <div className="timeline-meta" data-testid="provenance">
      <Pill tone={event.ai_drafted ? "ai" : "neutral"} icon={event.ai_drafted ? "spark" : "user"}>
        {event.ai_drafted ? "AI-drafted" : "Human-recorded"}
      </Pill>
      <span>{event.authorship}</span>
      <time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString()}</time>
      <span title={event.source}>from {event.source_label}</span>
    </div>
  );
}
