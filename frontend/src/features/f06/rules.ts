import { MIN_NOTE } from "./types";
import type { Decision } from "./types";

export function noteOk(note: string): boolean {
  return note.trim().length >= MIN_NOTE;
}

export const DECISION_LABEL: Record<Decision, string> = {
  continue: "Continue",
  hold: "Hold",
  stop: "Stop",
  change: "Change",
};

/** Shown to a person after a decision: deciding is not ordering. */
export function decisionText(decision: Decision | null): string {
  return decision ? DECISION_LABEL[decision] : "";
}
