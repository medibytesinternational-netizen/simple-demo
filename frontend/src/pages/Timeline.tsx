import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "../api";
import { useEvidence } from "../components/Evidence";
import { usePatientId } from "../session";
import { buildTimelineQuery, hasFilters } from "../features/f16/filters";
import { ProvenanceFacts } from "../features/f16/Provenance";
import { NO_FILTERS, type TimelineFilters, type TimelineResponse } from "../features/f16/types";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, Field, ListRow, Menu, MenuItem, Panel, Pill, Skeleton, Toolbar } from "../components/ui";
import type { TimelineEventF16 } from "../features/f16/types";
import { Icon } from "../components/icons";

function eventTone(type: string) {
  if (type === "lab_result") return "lab";
  if (["consult_note", "admission_note", "round_note", "progress_note", "nursing_summary", "nursing_chart", "investigation_review", "discharge_summary"].includes(type)) return "ai";
  if (["alert", "billing", "referral_consult"].includes(type)) return "critical";
  if (["consent", "referral_update", "device_reading"].includes(type)) return "";
  return "";
}

function fmt(value: string) {
  const date = new Date(value);
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function TimelinePage() {
  const { showEvent } = useEvidence();
  const patientId = usePatientId();
  const [filters, setFilters] = useState<TimelineFilters>(NO_FILTERS);
  const timeline = useQuery<TimelineResponse>({
    queryKey: ["timeline", patientId, filters],
    queryFn: () => get<TimelineResponse>(`/patients/${patientId}/timeline?${buildTimelineQuery(filters)}`),
    enabled: !!patientId,
    placeholderData: (previous) => previous,
  });
  const facets = timeline.data?.facets;
  const events = (timeline.data?.events || []).filter((event) => event.type !== "transcript");
  const days = groupByDay(events);
  const activeFilterCount = (filters.source ? 1 : 0) + (filters.after ? 1 : 0) + (filters.before ? 1 : 0);
  const typeFacets = (facets?.types || []).filter((type) => type !== "transcript");
  const quickTypes = typeFacets.slice(0, 2);
  const toggleType = (type: string) =>
    setFilters((current) => ({
      ...current,
      types: current.types.includes(type) ? current.types.filter((item) => item !== type) : [type],
    }));

  return (
    <>
      <PageHeader
        title="Patient chart"
        description="Everything recorded for this patient, newest first. Select any event to see where it came from."
        actions={<>
          <Link className="btn btn-primary" to="/notes?tab=consult">Start consultation</Link>
          <Link className="btn" to="/notes?tab=round">Ward round</Link>
        </>}
      />

      <div className="pg-timeline with-rail">
        <Panel
          title="Clinical event stream"
          count={events.length}
          sub="Approved events, newest first. Select a title to inspect its source."
          actions={<Pill icon="audit">Append-only</Pill>}
        >
          <div data-testid="timeline-filters">
            <Toolbar label="Timeline filters">
              <div className="toolbar-group tl-types" role="group" aria-label="Quick event filters">
                {quickTypes.map((type) => (
                  <button
                    key={type}
                    type="button"
                    className="chip"
                    aria-pressed={filters.types.includes(type)}
                    onClick={() => toggleType(type)}
                  >
                    {filters.types.includes(type) ? <Icon name="check" size={13} /> : null}
                    {type.replaceAll("_", " ")}
                  </button>
                ))}
              </div>
              <span className="toolbar-spacer" />
              <Menu label="Filter" icon="filter" badge={activeFilterCount} align="right">
                {(close) => (
                  <>
                    <div className="menu-body">
                      <Field label="Event type" htmlFor="tl-type">
                        <select
                          id="tl-type"
                          className="select"
                          value={filters.types[0] || ""}
                          onChange={(event) => setFilters({ ...filters, types: event.target.value ? [event.target.value] : [] })}
                        >
                          <option value="">All event types</option>
                          {typeFacets.map((type) => (
                            <option key={type} value={type}>{type.replaceAll("_", " ")}</option>
                          ))}
                        </select>
                      </Field>
                      <Field label="Source" htmlFor="tl-source">
                        <select
                          id="tl-source"
                          className="select"
                          value={filters.source}
                          onChange={(event) => setFilters({ ...filters, source: event.target.value })}
                        >
                          <option value="">All sources</option>
                          {(facets?.sources || []).map((item) => (
                            <option key={item.source} value={item.source}>{item.label}</option>
                          ))}
                        </select>
                      </Field>
                      <Field label="From" htmlFor="tl-after" hint="Includes this day.">
                        <input id="tl-after" className="input" type="date" value={filters.after} onChange={(event) => setFilters({ ...filters, after: event.target.value })} />
                      </Field>
                      <Field label="Before" htmlFor="tl-before" hint="Up to, not including, this day.">
                        <input id="tl-before" className="input" type="date" value={filters.before} onChange={(event) => setFilters({ ...filters, before: event.target.value })} />
                      </Field>
                    </div>
                    {hasFilters(filters) ? (
                      <>
                        <div className="menu-sep" />
                        <MenuItem icon="close" onSelect={() => { setFilters(NO_FILTERS); close(); }}>Clear filters</MenuItem>
                      </>
                    ) : null}
                  </>
                )}
              </Menu>
            </Toolbar>
          </div>

          <div className="panel-body">
            {timeline.isLoading ? <Skeleton variant="rows" count={5} /> : null}
            {!timeline.isLoading && !events.length && hasFilters(filters) ? (
              <EmptyState
                icon="filter"
                title="No events match these filters."
                action={<button type="button" className="btn btn-sm" onClick={() => setFilters(NO_FILTERS)}>Clear filters</button>}
              >
                Try another event type or a wider date range.
              </EmptyState>
            ) : null}
            {!timeline.isLoading && !events.length && !hasFilters(filters) ? (
              <EmptyState
                icon="chart"
                title="No events yet."
                action={<Link className="btn btn-primary" to="/notes?tab=consult">Start consultation</Link>}
              >
                Start a consultation to write the first note, or load rehearsal data from Workspace controls.
              </EmptyState>
            ) : null}
            {events.length ? (
              <div className="timeline timeline-scroll">
                {days.map((day, index) => (
                  <section className="day-group" key={`${day.key}-${index}`} aria-label={day.label}>
                    <h3 className="day-head">
                      <span>{day.label}</span>
                      <span className="day-count">{day.events.length} {day.events.length === 1 ? "event" : "events"}</span>
                    </h3>
                    <div className="rows">
                      {day.events.map((event) => (
                        <ListRow
                          key={event.id}
                          icon={eventIcon(event.type)}
                          tone={rowTone(eventTone(event.type))}
                          title={
                            <button type="button" className="lrow-title-btn" onClick={() => showEvent(event.id)}>
                              {event.title}
                            </button>
                          }
                          meta={
                            <span className="pill-row">
                              <Pill>{event.type.replaceAll("_", " ")}</Pill>
                              {event.status === "superseded" ? (
                                event.superseded_by ? (
                                  <button
                                    type="button"
                                    className="badge badge-warning tl-superseded"
                                    title="Open the version that replaced this one"
                                    onClick={() => showEvent(event.superseded_by!)}
                                  >
                                    superseded by {event.superseded_by}
                                  </button>
                                ) : (
                                  <Pill tone="warning">superseded</Pill>
                                )
                              ) : null}
                            </span>
                          }
                          body={event.body_text ? <span className="tl-preview">{event.body_text}</span> : undefined}
                          chips={<ProvenanceFacts event={event} />}
                          side={
                            <span className="tl-when">
                              <time className="event-time" dateTime={event.occurred_at} title={fmt(event.occurred_at)}>{timeOf(event.occurred_at)}</time>
                            </span>
                          }
                        />
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            ) : null}
          </div>
        </Panel>

        <aside className="rail rail-sticky" aria-label="Patient summary">
          <Panel title="Care pathway" sub="Each step ends in an approval that writes to this timeline.">
            <ol className="tl-path">
              {PATHWAY.map((step) => (
                <li key={step.to}>
                  <Link className="tl-path-link" to={step.to}>
                    <Icon name={step.icon} size={16} />
                    <span>{step.label}</span>
                    <Icon name="chevron" size={14} className="tl-path-chev" />
                  </Link>
                </li>
              ))}
            </ol>
          </Panel>
        </aside>
      </div>
    </>
  );
}

const PATHWAY = [
  { label: "Consultation", to: "/notes?tab=consult", icon: "consult" },
  { label: "Admission", to: "/admission", icon: "admission" },
  { label: "Safety alerts", to: "/safety?tab=alerts", icon: "safety" },
  { label: "Ward round", to: "/notes?tab=round", icon: "round" },
  { label: "Documents", to: "/documents?tab=inbound", icon: "scan" },
  { label: "Discharge", to: "/discharge", icon: "discharge" },
  { label: "Claim review", to: "/revenue?tab=claim", icon: "billing" },
];

const EVENT_ICONS: Record<string, string> = {
  lab_result: "lab",
  consult_note: "consult",
  admission_note: "admission",
  round_note: "round",
  progress_note: "progress",
  nursing_summary: "round",
  nursing_chart: "round",
  nursing_note: "round",
  investigation_review: "lab",
  discharge_summary: "discharge",
  alert: "alert",
  billing: "billing",
  referral_consult: "referral",
  referral_update: "referral",
  consent: "edit",
  device_reading: "icu",
  med_order: "pill",
  medication_administration: "pill",
  reconciliation_decision: "pill",
  allergy_record: "alert",
  document_request: "request",
  document_review: "scan",
};

function eventIcon(type: string) {
  return EVENT_ICONS[type] || "chart";
}

/** Same tones as the old timeline dot: AI notes, labs (amber), critical events, else neutral. */
function rowTone(tone: string): "ai" | "warning" | "critical" | undefined {
  if (tone === "ai") return "ai";
  if (tone === "lab") return "warning";
  if (tone === "critical") return "critical";
  return undefined;
}

function timeOf(value: string) {
  return new Date(value).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** Presentational grouping of the already-filtered list; order is kept. */
function groupByDay(events: TimelineEventF16[]) {
  const days: { key: string; label: string; events: TimelineEventF16[] }[] = [];
  for (const event of events) {
    const date = new Date(event.occurred_at);
    const key = date.toDateString();
    const last = days[days.length - 1];
    if (last && last.key === key) last.events.push(event);
    else days.push({ key, label: date.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" }), events: [event] });
  }
  return days;
}
