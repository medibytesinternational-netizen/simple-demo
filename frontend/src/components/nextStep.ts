// Single source of truth for "what comes next" navigation.
export type NextStep = { label: string; to: string };

/** Keyed by Notes tab key or page id. */
export const NEXT_STEP: Record<string, NextStep> = {
  consult: { label: "Go to IPD / Ward round", to: "/notes?tab=round" },
  round: { label: "Review ward tasks", to: "/tasks" },
  progress: { label: "Check discharge readiness", to: "/discharge" },
  icu: { label: "Check discharge readiness", to: "/discharge" },
  referral: { label: "Back to patient overview", to: "/patient" },
  labs: { label: "Open safety alerts", to: "/safety?tab=alerts" },
  tasks: { label: "Go to discharge", to: "/discharge" },
  discharge: { label: "Open billing", to: "/revenue?tab=claim" },
};

/** Where each safety rule's issue gets fixed. */
export const ALERT_TARGET: Record<string, NextStep> = {
  R1: { label: "Review medicines", to: "/safety?tab=meds" },
  R2: { label: "Review medicines", to: "/safety?tab=meds" },
  R3: { label: "Review labs", to: "/notes?tab=labs" },
  R4: { label: "Review medicines", to: "/safety?tab=meds" },
  R5: { label: "Open chart", to: "/timeline" },
  R6: { label: "Open tasks", to: "/tasks" },
};
