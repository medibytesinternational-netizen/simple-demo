import type { Alert } from "../../types";

export type DismissCategory = "false_positive" | "known_and_accepted" | "acted_on";

export const DISMISS_CATEGORIES: { value: DismissCategory; label: string }[] = [
  { value: "false_positive", label: "False alarm: the alert was wrong" },
  { value: "known_and_accepted", label: "Already known: the risk is understood and accepted" },
  { value: "acted_on", label: "Acted on: I changed the care because of it" },
];

export const CATEGORY_LABEL: Record<DismissCategory, string> = {
  false_positive: "False alarm",
  known_and_accepted: "Already known",
  acted_on: "Acted on",
};

// The shared Alert type has no "resolved" status, resolution text or dismissal category.
export type AlertRow = Omit<Alert, "status"> & {
  status: Alert["status"] | "resolved";
  resolution?: string | null;
  dismissal_category?: DismissCategory | null;
};

export const MIN_REASON = 10;
