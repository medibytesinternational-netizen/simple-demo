export const MIN_NOTE = 10;

export type Decision = "continue" | "hold" | "stop" | "change";
export type OrderAction = "start" | "stop" | "change";
export type DoseStatus = "given" | "held" | "refused";

export type Discrepancy = {
  id: string;
  kind: string;
  drug: string;
  home_med: string;
  current_order: string | null;
  field: string;
  home_value: string;
  current_value: string;
  explanation: string;
  recommended_action: string;
  evidence_event_ids: string[];
  status: "open" | "resolved";
  decision: Decision | null;
  note: string | null;
  decided_by: string | null;
  decided_at: string | null;
  earlier_decision: { decision: Decision; decided_by: string | null; decided_at: string | null } | null;
};

export type ReconciliationResult = {
  discrepancies: Discrepancy[];
  unresolved_count: number;
  summary: string;
};

export type ProposedOrderChange = {
  decision: Decision;
  action: string;
  drug: string;
  current_order: string | null;
  message: string;
};

export type ActiveMedicine = {
  event_id: string;
  drug: string;
  dose: string;
  route: string;
  frequency: string;
  indication: string;
};

export type Administration = {
  event_id: string;
  drug: string;
  dose: string;
  route: string;
  status: DoseStatus;
  given_at: string;
  order_event_id: string;
  note: string;
  recorded_by: string;
};

export type NewAlert = { id: string; rule_id: string; severity: string; title: string; explanation: string };
