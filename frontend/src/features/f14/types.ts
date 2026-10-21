import type { HospitalDashboard } from "../../types";

/** The lead's HospitalDashboard type plus the counts F14 adds to each row and to the summary. */
export type F14Row = HospitalDashboard["patients"][number] & {
  pending_tasks: number;
  draft_discharges: number;
  medicine_discrepancies: number;
};

export type F14Dashboard = Omit<HospitalDashboard, "patients" | "summary"> & {
  patients: F14Row[];
  summary: HospitalDashboard["summary"] & {
    pending_tasks: number;
    draft_discharges: number;
    medicine_discrepancies: number;
  };
};

export type AlertQualityRule = {
  rule_id: string;
  opened: number;
  open: number;
  false_positive: number;
  known_and_accepted: number;
  acted_on: number;
  auto_resolved: number;
  precision: number | null;
};

export type AlertQuality = {
  rules: AlertQualityRule[];
  sample_size: number;
  note: string;
};
