import { createContext, useContext, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "../api";
import type { EventDetail } from "../features/f16/types";
import { ProvenanceFacts } from "../features/f16/Provenance";

type EvidenceCtx = {
  selectedEventId: string | null;
  showEvent: (eventId: string) => void;
  close: () => void;
};

const EvidenceContext = createContext<EvidenceCtx>({
  selectedEventId: null,
  showEvent: () => undefined,
  close: () => undefined,
});

export function EvidenceProvider({ children }: { children: ReactNode }) {
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  return (
    <EvidenceContext.Provider
      value={{
        selectedEventId,
        showEvent: (eventId) => setSelectedEventId(eventId),
        close: () => setSelectedEventId(null),
      }}
    >
      {children}
    </EvidenceContext.Provider>
  );
}

export function useEvidence() {
  return useContext(EvidenceContext);
}

export function EvidenceChip({
  eventIds,
  segmentIds,
  label,
}: {
  eventIds?: string[];
  segmentIds?: string[];
  label?: string;
}) {
  const { showEvent } = useEvidence();
  const ids = (eventIds || []).filter(Boolean);
  const segments = (segmentIds || []).filter(Boolean);
  if (!ids.length && !segments.length) {
    return <span className="evidence-chip unsourced">No source</span>;
  }
  if (!ids.length) {
    return <span className="badge badge-neutral">{segments.length} transcript refs</span>;
  }
  return (
    <button
      className="evidence-chip"
      title={ids.join(", ")}
      onClick={(event) => {
        event.stopPropagation();
        showEvent(ids[0]);
      }}
    >
      {label || `${ids.length} source${ids.length === 1 ? "" : "s"}`}
    </button>
  );
}

export function EvidenceDrawer() {
  const { selectedEventId, showEvent, close } = useEvidence();
  const query = useQuery({
    queryKey: ["event", selectedEventId],
    queryFn: () => get<EventDetail>(`/events/${selectedEventId}`),
    enabled: Boolean(selectedEventId),
  });
  if (!selectedEventId) return null;
  const event = query.data;
  return (
    <>
      <div className="drawer-backdrop" onClick={close} />
      <aside className="drawer">
        <div className="drawer-head">
          <div>
            <div className="card-title">Source event</div>
            <div className="small muted">{selectedEventId}</div>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={close}>
            Close
          </button>
        </div>
        <div className="drawer-body">
          {query.isLoading ? <div className="loading">Loading source…</div> : null}
          {query.error ? <div className="error-box">{String(query.error)}</div> : null}
          {event ? (
            <>
              <div className="flex items-center gap-2 mb-2">
                <span className={`badge ${event.status === "approved" ? "badge-success" : "badge-neutral"}`}>
                  {event.status}
                </span>
                <span className="badge badge-ai" title={event.source}>{event.source_label}</span>
                <span className="badge badge-neutral">{event.type}</span>
              </div>
              <div className="fs-20" style={{ fontWeight: 650, marginBottom: 4 }}>
                {event.title}
              </div>
              <div className="mb-3">
                <ProvenanceFacts event={event} />
              </div>
              {event.body_text ? <p className="fs-13" style={{ lineHeight: 1.6 }}>{event.body_text}</p> : null}
              <div className="section-label">Raw payload</div>
              <pre className="code" style={{ whiteSpace: "pre-wrap", padding: 10, maxHeight: 360, overflow: "auto" }}>
                {JSON.stringify(event.payload, null, 2)}
              </pre>
              <div className="section-label">Provenance</div>
              <dl className="kv">
                <dt>Author type</dt>
                <dd>{event.author_type}</dd>
                <dt>Recorded by</dt>
                <dd>{event.recorded_by}</dd>
                <dt>Drafted by</dt>
                <dd>{event.drafted_by || "—"}</dd>
                <dt>Approved by</dt>
                <dd>{event.approved_by || "—"}</dd>
                <dt>Source</dt>
                <dd>{event.source_label} <span className="mono small">({event.source})</span></dd>
                <dt>Event id</dt>
                <dd className="mono">{event.id}</dd>
                <dt>Encounter</dt>
                <dd className="mono">{event.encounter_id || "—"}</dd>
                {event.superseded_by ? (
                  <>
                    <dt>Superseded by</dt>
                    <dd>
                      <button className="btn btn-ghost btn-sm mono" onClick={() => showEvent(event.superseded_by!)}>
                        {event.superseded_by}
                      </button>
                    </dd>
                  </>
                ) : null}
                {event.supersedes?.length ? (
                  <>
                    <dt>Supersedes</dt>
                    <dd>
                      {event.supersedes.map((version) => (
                        <div key={version.id}>
                          <button className="btn btn-ghost btn-sm mono" onClick={() => showEvent(version.id)}>
                            {version.id}
                          </button>
                          <span className="small muted"> {new Date(version.occurred_at).toLocaleString()} · {version.recorded_by}</span>
                        </div>
                      ))}
                    </dd>
                  </>
                ) : null}
              </dl>
            </>
          ) : null}
        </div>
      </aside>
    </>
  );
}
