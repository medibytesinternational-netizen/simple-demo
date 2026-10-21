import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "../api";
import type { AppState } from "../types";
import { useEvidence } from "../components/Evidence";
import { usePatientId } from "../session";
import { buildTimelineQuery, hasFilters } from "../features/f16/filters";
import { ProvenanceFacts } from "../features/f16/Provenance";
import { NO_FILTERS, type TimelineFilters, type TimelineResponse } from "../features/f16/types";

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
  const state = useQuery<AppState>({
    queryKey: ["state", patientId],
    queryFn: () => get<AppState>(`/patients/${patientId}/state`),
    enabled: !!patientId,
  });
  const [filters, setFilters] = useState<TimelineFilters>(NO_FILTERS);
  const timeline = useQuery<TimelineResponse>({
    queryKey: ["timeline", patientId, filters],
    queryFn: () => get<TimelineResponse>(`/patients/${patientId}/timeline?${buildTimelineQuery(filters)}`),
    enabled: !!patientId,
    placeholderData: (previous) => previous,
  });
  const facets = timeline.data?.facets;
  const toggleType = (type: string) =>
    setFilters((current) => ({
      ...current,
      types: current.types.includes(type) ? current.types.filter((item) => item !== type) : [...current.types, type],
    }));

  const data = state.data;
  const events = (timeline.data?.events || []).filter((event) => event.type !== "transcript");
  const egfr = data?.latest_labs.find((lab) => lab.name.toLowerCase() === "egfr");
  const openAlerts = data?.alerts.filter((alert) => alert.status === "open").length || 0;
  const overdue = data?.tasks.filter((task) => task.is_overdue).length || 0;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Patient timeline</h1>
          <div className="page-sub">
            Append-only clinical record. Every feature reads this timeline through a whitelisted context slice. Superseded events stay visible.
          </div>
        </div>
        <div className="page-actions">
          <Link className="btn btn-primary" to="/notes?tab=consult">Start consultation</Link>
          <Link className="btn" to="/notes?tab=round">Round handover</Link>
        </div>
      </div>

      <div className="grid-4 mb-3">
        <div className="card stat">
          <div className="stat-label">Active medications</div>
          <div className="stat-value">{data?.active_meds.length ?? "—"}</div>
          <div className="stat-note">Current inpatient orders</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Latest eGFR</div>
          <div className="stat-value mono">{egfr ? egfr.value : "—"}</div>
          <div className="stat-note">{egfr ? `${egfr.review_status} · ${egfr.collected_at.slice(0, 10)}` : "No result"}</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Open alerts</div>
          <div className="stat-value" style={{ color: openAlerts ? "var(--critical)" : undefined }}>{openAlerts}</div>
          <div className="stat-note">{data?.alerts.filter((alert) => alert.status === "dismissed").length || 0} dismissed with reason</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Tasks overdue</div>
          <div className="stat-value" style={{ color: overdue ? "var(--warning)" : undefined }}>{overdue}</div>
          <div className="stat-note">{data?.tasks.length || 0} tasks total</div>
        </div>
      </div>

      <div className="split-main">
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Clinical event stream</div>
              <div className="card-sub">{events.length} approved events · click any event to inspect its source</div>
            </div>
            <span className="badge badge-neutral">append-only</span>
          </div>
          <div className="card-pad" style={{ borderBottom: "1px solid var(--border, #e5e7eb)" }} data-testid="timeline-filters">
            <div className="pill-row">
              {(facets?.types || []).filter((type) => type !== "transcript").map((type) => (
                <button
                  key={type}
                  className={`btn btn-sm ${filters.types.includes(type) ? "btn-primary" : ""}`}
                  aria-pressed={filters.types.includes(type)}
                  onClick={() => toggleType(type)}
                >
                  {type.replaceAll("_", " ")}
                </button>
              ))}
            </div>
            <div className="button-row mt-3">
              <label className="small">
                Source{" "}
                <select
                  className="select"
                  value={filters.source}
                  onChange={(event) => setFilters({ ...filters, source: event.target.value })}
                >
                  <option value="">All sources</option>
                  {(facets?.sources || []).map((item) => (
                    <option key={item.source} value={item.source}>{item.label}</option>
                  ))}
                </select>
              </label>
              <label className="small">
                From{" "}
                <input className="input" type="date" value={filters.after} onChange={(event) => setFilters({ ...filters, after: event.target.value })} />
              </label>
              <label className="small">
                Before{" "}
                <input className="input" type="date" value={filters.before} onChange={(event) => setFilters({ ...filters, before: event.target.value })} />
              </label>
              {hasFilters(filters) ? (
                <button className="btn btn-ghost btn-sm" onClick={() => setFilters(NO_FILTERS)}>Clear filters</button>
              ) : null}
            </div>
          </div>
          <div className="card-pad" style={{ maxHeight: 760, overflowY: "auto" }}>
            {timeline.isLoading ? <div className="loading">Loading timeline…</div> : null}
            {!timeline.isLoading && !events.length && hasFilters(filters) ? (
              <div className="empty">
                <div className="empty-title">No events match these filters.</div>
              </div>
            ) : null}
            {!timeline.isLoading && !events.length && !hasFilters(filters) ? (
              <div className="empty">
                <div className="empty-title">The timeline is empty.</div>
                <div>Use the Demo menu to load rehearsal data, or start with a consultation.</div>
                <div className="mt-3"><Link className="btn btn-primary" to="/notes?tab=consult">Start consultation</Link></div>
              </div>
            ) : null}
            <div className="timeline">
              {events.map((event) => (
                <div className="timeline-item" key={event.id}>
                  <div className="timeline-time">{fmt(event.occurred_at)}</div>
                  <div className="timeline-rail"><span className={`timeline-dot ${eventTone(event.type)}`} /></div>
                  <div className="timeline-card" onClick={() => showEvent(event.id)}>
                    <div className="timeline-card-head">
                      <span className="timeline-title">{event.title}</span>
                      <span className="badge badge-neutral">{event.type.replaceAll("_", " ")}</span>
                      {event.status === "superseded" ? (
                        event.superseded_by ? (
                          <button
                            className="badge badge-warning"
                            title="Open the version that replaced this one"
                            onClick={(click) => {
                              click.stopPropagation();
                              showEvent(event.superseded_by!);
                            }}
                          >
                            superseded by {event.superseded_by}
                          </button>
                        ) : (
                          <span className="badge badge-warning">superseded</span>
                        )
                      ) : null}
                    </div>
                    {event.body_text ? <div className="timeline-body">{event.body_text}</div> : null}
                    <ProvenanceFacts event={event} />
                    <div className="timeline-meta">
                      <span className="mono">{event.id}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="flex-col gap-3">
          <div className="card">
            <div className="card-head">
              <div className="card-title">Current state</div>
              <span className="badge badge-ai">resolved from timeline</span>
            </div>
            <div className="card-pad">
              <div className="section-label">Problems</div>
              <div className="pill-row">
                {data?.patient.problems.map((problem) => <span className="badge badge-neutral" key={problem}>{problem}</span>)}
              </div>
              <div className="section-label">Allergies</div>
              <div className="pill-row">
                {data?.patient.allergies.map((allergy) => <span className="badge badge-critical" key={allergy}>{allergy}</span>)}
              </div>
              <div className="section-label">Active medications</div>
              {data?.active_meds.map((med) => (
                <div className="check-row" key={med.event_id}>
                  <span style={{ flex: 1 }}>{med.drug}</span>
                  <span className="mono small">{med.dose} {med.frequency}</span>
                  <button className="btn btn-ghost btn-sm" onClick={() => showEvent(med.event_id)}>source</button>
                </div>
              ))}
              <div className="section-label">Latest results</div>
              {data?.latest_labs.map((lab) => (
                <div className="check-row" key={lab.event_id}>
                  <span style={{ flex: 1 }}>{lab.name}</span>
                  <span className="mono small">{lab.value} {lab.unit}</span>
                  <span className={`badge ${lab.review_status === "unreviewed" ? "badge-warning" : lab.flag === "high" || lab.flag === "low" ? "badge-neutral" : "badge-success"}`}>
                    {lab.review_status === "unreviewed" ? "unreviewed" : lab.flag}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="card-head"><div className="card-title">Join the flow</div></div>
            <div className="card-pad">
              <div className="small muted" style={{ lineHeight: 1.7 }}>
                Consultation → admission → alerts → reconciliation → round → documents → discharge → revenue.
                Every screen ends in an approval that writes to this timeline, and the next screen reads it.
              </div>
              <div className="button-row mt-3">
                <Link className="btn btn-sm" to="/safety">Open safety</Link>
                <Link className="btn btn-sm" to="/documents">Documents</Link>
                <Link className="btn btn-sm" to="/discharge">Discharge</Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
