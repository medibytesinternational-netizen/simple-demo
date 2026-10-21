import type { AppTask } from "../../types";
import { MIN_REASON } from "./types";
import type { EscalationKind } from "./types";

export const AUTO_REASON_PREFIX = "Automatically escalated";

export function isClosed(task: AppTask): boolean {
  return task.status === "completed" || task.status === "cancelled";
}

/** Automatic when the engine wrote the reason; manual when a person did. Null when never escalated. */
export function escalationKind(task: AppTask): EscalationKind | null {
  if (!task.escalation_level) return null;
  return (task.escalation_reason || "").startsWith(AUTO_REASON_PREFIX) ? "automatic" : "manual";
}

/** Only the assignee acknowledges (the server enforces this too). */
export function canAcknowledge(task: AppTask, userName: string | undefined): boolean {
  return !!userName && !!task.assigned_to && task.assigned_to === userName;
}

export function reasonOk(reason: string): boolean {
  return reason.trim().length >= MIN_REASON;
}
