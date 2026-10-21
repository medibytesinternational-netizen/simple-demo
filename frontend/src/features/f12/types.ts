import type { ClaimPrep } from "../../types";

/** One source behind a contradiction: the event, and the sentence quoted from it. */
export type ContradictionEvidence = {
  event_id: string;
  type: string;
  title: string;
  quote: string;
};

export type F12Contradiction = ClaimPrep["contradictions"][number] & {
  evidence?: ContradictionEvidence[];
};

export type F12TpaReview = ClaimPrep["tpa_review"] & {
  evidence_event_ids?: string[];
};

export function tpaLabel(status: string | undefined): string {
  return (status || "unknown").replaceAll("_", " ");
}
