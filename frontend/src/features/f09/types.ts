export const MIN_REASON = 10;

export type ReadinessItem = { key: string; label: string; present: boolean; source: string };

export type WarningItem = { id: string; title: string };

export type Warnings = {
  open_critical_alerts: WarningItem[];
  open_tasks: WarningItem[];
  unresolved_medicine_differences: WarningItem[];
};

export type Readiness = {
  items: ReadinessItem[];
  warnings: Warnings;
  /** Required documentation exists. Warnings do not clear it; they need a written reason. */
  ready: boolean;
  needs_override: boolean;
  already_signed: boolean;
  encounter_status: string;
};

export function reasonOk(reason: string): boolean {
  return reason.trim().length >= MIN_REASON;
}

export function warningCount(warnings: Warnings | undefined): number {
  if (!warnings) return 0;
  return (
    warnings.open_critical_alerts.length +
    warnings.open_tasks.length +
    (warnings.unresolved_medicine_differences ?? []).length
  );
}
