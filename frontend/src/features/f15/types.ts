export const MIN_REASON = 10;

export type ReasonMode = "escalate" | "reopen";

export type ReasonTarget = { id: string; mode: ReasonMode };

export type EscalationKind = "automatic" | "manual";
