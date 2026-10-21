import type { TimelineEvent } from "../../types";

// What GET /patients/{id}/timeline and GET /events/{id} return for every event.
export type Provenance = {
  recorded_by: string;
  drafted_by: string | null;
  approved_by: string | null;
  source_label: string;
  superseded_by: string | null;
  authorship: string;
  ai_drafted: boolean;
};

export type TimelineEventF16 = TimelineEvent & Provenance;

export type SupersededVersion = {
  id: string;
  title: string;
  status: string;
  occurred_at: string;
  recorded_by: string;
  source_label: string;
};

export type EventDetail = TimelineEventF16 & { supersedes: SupersededVersion[] };

export type TimelineFacets = {
  types: string[];
  sources: { source: string; label: string }[];
};

export type TimelineResponse = {
  events: TimelineEventF16[];
  count: number;
  facets: TimelineFacets;
  filters: { types: string[]; source: string | null; before: string | null; after: string | null };
};

export type TimelineFilters = {
  types: string[];
  source: string;
  after: string; // a date, inclusive
  before: string; // a date, exclusive
};

export const NO_FILTERS: TimelineFilters = { types: [], source: "", after: "", before: "" };
