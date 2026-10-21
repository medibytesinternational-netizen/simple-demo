import type { TimelineFilters } from "./types";

/** The query string for the timeline route; empty filters are left out. */
export function buildTimelineQuery(filters: TimelineFilters, limit = 250): string {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (filters.types.length) params.set("types", filters.types.join(","));
  if (filters.source) params.set("source", filters.source);
  if (filters.after) params.set("after", filters.after);
  if (filters.before) params.set("before", filters.before);
  return params.toString();
}

export function hasFilters(filters: TimelineFilters): boolean {
  return Boolean(filters.types.length || filters.source || filters.after || filters.before);
}
