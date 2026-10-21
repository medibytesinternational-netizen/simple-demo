export type Claim = {
  text: string;
  source_event_ids?: string[];
  source_segment_ids?: string[];
  confidence?: number;
  human_authored?: boolean;
};

export type Meta = {
  product: string;
  patient: Patient;
  encounter: Encounter;
  demo_now: string;
  server_now: string;
  llm_mode: "live" | "cached";
  model: string;
  live_available: boolean;
  demo_user: string;
  demo_role: string;
  features: string[];
  disclaimer: string;
};

export type Patient = {
  id: string;
  mrn: string;
  name: string;
  age: number;
  sex: string;
  allergies: string[];
  problems: string[];
  weight_kg?: number;
  height_cm?: number;
  code_status?: string;
};

export type Encounter = {
  id: string;
  kind: string;
  ward: string;
  bed: string;
  attending: string;
  admitted_at: string;
  discharged_at?: string | null;
  status: string;
};

export type Medication = {
  event_id: string;
  drug: string;
  dose: string;
  route: string;
  frequency: string;
  indication: string;
  kind: string;
  status: string;
  started_at: string;
};

export type Lab = {
  event_id: string;
  name: string;
  value: string | number;
  unit: string;
  reference_range: string;
  flag: string;
  review_status: string;
  collected_at: string;
};

export type AppTask = {
  id: string;
  title: string;
  detail: string;
  status: string;
  priority: string;
  due_at?: string | null;
  owner?: string;
  source_event_id?: string | null;
  accepted_from_draft_id?: string | null;
  completed_at?: string | null;
  is_overdue?: boolean;
  assigned_to?: string | null;
  assigned_at?: string | null;
  acknowledged_at?: string | null;
  acknowledged_by?: string | null;
  escalation_level?: number;
  escalated_at?: string | null;
  escalation_reason?: string | null;
};

export type Alert = {
  id: string;
  rule_id: string;
  severity: "critical" | "warning";
  status: "open" | "acknowledged" | "dismissed";
  title: string;
  explanation: string;
  recommended_action: string;
  evidence_event_ids: string[];
  acknowledged_by?: string | null;
  dismissed_by?: string | null;
  dismissal_reason?: string | null;
  created_at: string;
  resolved_at?: string | null;
};

export type AppState = {
  patient: Patient;
  encounter: Encounter;
  home_meds: Medication[];
  active_meds: Medication[];
  latest_labs: Lab[];
  unreviewed_labs: Lab[];
  vitals: { event_id: string; payload: any; occurred_at: string } | null;
  tasks: AppTask[];
  alerts: Alert[];
  documents: DocumentSummary[];
  notes: Record<string, { event_id: string; title: string; occurred_at: string; payload: any }>;
  discharge_signed: boolean;
  discharge_event_id?: string | null;
};

export type DocumentSummary = {
  id: string;
  filename: string;
  doc_type: string;
  ocr_status: string;
  uploaded_at: string;
  field_count: number;
};

export type OcrField = {
  name: string;
  value: string;
  unit: string;
  reference_range: string;
  collected_at: string;
  confidence: number;
  page?: number;
  bbox?: number[];
  confirmed?: boolean;
};

export type DocumentDetail = {
  id: string;
  filename: string;
  mime: string;
  doc_type: string;
  ocr_status: string;
  raw_text: string;
  extracted: { document_type?: string; fields: OcrField[]; raw_text?: string };
  uploaded_by: string;
  uploaded_at: string;
  confirmed_by?: string | null;
  confirmed_at?: string | null;
  image_url: string;
};

export type DocumentRequest = {
  id: string;
  request_type: string;
  records_requested: string[];
  recipient: string;
  justification: string;
  due_at?: string | null;
  status: string;
  matched_document_id?: string | null;
  draft_id?: string | null;
  created_at: string;
  approved_by?: string;
};

export type InvestigationRequest = {
  id: string;
  request_type: string;
  study: string;
  indication: string;
  diagnosis: string;
  allergies_to_verify: Array<{
    substance: string;
    reaction?: string;
    source_event_id?: string;
    verified?: boolean;
  }>;
  priority: string;
  instructions: string;
  status: string;
  draft_id?: string | null;
  approved_by?: string;
  created_at: string;
  exported_at?: string | null;
};

export type TimelineEvent = {
  id: string;
  patient_id: string;
  encounter_id?: string;
  type: string;
  subtype?: string;
  title: string;
  body_text: string;
  payload: any;
  source: string;
  author_type: string;
  author_name: string;
  status: string;
  confidence?: number | null;
  supersedes_event_id?: string | null;
  occurred_at: string;
  created_at: string;
  approved_by?: string | null;
  approved_at?: string | null;
  document_id?: string | null;
};

export type Draft = {
  id: string;
  feature: string;
  patient_id: string;
  encounter_id?: string;
  status: "generating" | "draft_ready" | "human_edited" | "approved" | "rejected" | "model_unavailable";
  content: any;
  schema_version: string;
  prompt_version: string;
  model: string;
  llm_call_id?: string | null;
  evidence_event_ids: string[];
  created_from_event_ids: string[];
  edited_by?: string | null;
  approved_by?: string | null;
  rejected_reason?: string | null;
  committed_event_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type Reconciliation = {
  discrepancies: {
    id: string;
    kind: string;
    home_med: string;
    current_order?: string | null;
    explanation: string;
    evidence_event_ids: string[];
    field?: string | null;
    home_value?: string | null;
    current_value?: string | null;
    recommended_action?: string | null;
  }[];
  home_medications: Medication[];
  current_medications: Medication[];
  summary: string;
};

export type RequiredDoc = {
  key: string;
  label: string;
  present: boolean;
  evidence_event_ids: string[];
};

export type ClaimPrep = {
  status: string;
  required_documents: RequiredDoc[];
  missing_documents: RequiredDoc[];
  documented_procedures: { procedure: string; code: string; event_id: string; evidence_event_ids: string[] }[];
  billed_items: {
    id: string;
    code: string;
    description: string;
    amount: number;
    expected_amount?: number | null;
    documentation_event_ids: string[];
  }[];
  unbilled_procedures: { procedure: string; code: string; event_id: string; evidence_event_ids: string[] }[];
  underbilled_items: {
    id: string;
    code: string;
    description: string;
    billed_amount: number;
    expected_amount: number;
    variance: number;
    documentation_event_ids: string[];
    evidence_event_ids: string[];
  }[];
  unsupported_items: { id: string; code: string; description: string; amount: number; evidence_event_ids: string[] }[];
  contradictions: {
    id: string;
    kind: string;
    title: string;
    explanation: string;
    evidence_event_ids: string[];
  }[];
  tpa_review: { status: string; reviewer?: string | null; contradiction_count: number };
  total_amount: number;
  expected_total_amount: number;
  underbilled_amount: number;
  discharge_signed: boolean;
  reviews: { id: string; status: string; prepared_at?: string | null; reviewed_by?: string | null }[];
};

export type Leakage = {
  findings: {
    id: string;
    procedure: string;
    billing_status: "unbilled" | "underbilled" | "unsupported";
    explanation: string;
    evidence_event_ids: string[];
  }[];
  count: number;
  summary: string;
};

export type DashboardData = {
  patient: { name: string; mrn: string };
  encounter: { status: string; ward: string; bed: string };
  operational: {
    timeline_events: number;
    drafts_total: number;
    drafts_approved: number;
    open_alerts: number;
    dismissed_alerts: number;
    tasks_total: number;
    tasks_overdue: number;
    documents_pending: number;
    claim_gaps: number;
    llm_calls: number;
    avg_latency_ms: number;
  };
  illustrative: {
    clinician_minutes_saved: number;
    revenue_at_risk: number;
    leakage_identified: number;
    note: string;
  };
  claim: {
    status: string;
    missing_documents: string[];
    total_amount: number;
    expected_total_amount: number;
    underbilled_items: Array<{ id: string; description: string; variance: number }>;
    underbilled_amount: number;
    contradictions: Array<{ id: string; title: string }>;
  };
  recent_audit: AuditEntry[];
};

export type HospitalDashboard = {
  hospital: { name: string; as_of: string };
  summary: {
    active_encounters: number;
    patients: number;
    wards: Record<string, number>;
    pending_drafts: number;
    overdue_tasks: number;
    escalated_tasks: number;
    open_alerts: number;
    critical_alerts: number;
    pending_documents: number;
    open_referrals: number;
    pending_investigations: number;
    claim_gaps: number;
    discharge_reviews: number;
  };
  patients: Array<{
    patient_id: string;
    name: string;
    mrn: string;
    age: number;
    sex: string;
    encounter_id?: string | null;
    kind?: string | null;
    ward?: string | null;
    bed?: string | null;
    encounter_status: string;
    open_alerts: number;
    critical_alerts: number;
    overdue_tasks: number;
    escalated_tasks: number;
    pending_drafts: number;
    pending_documents: number;
    open_referrals: number;
    pending_investigations: number;
    claim_gaps: number;
    flags: string[];
  }>;
  claim: {
    status: string;
    missing_documents: string[];
    total_amount: number;
    expected_total_amount: number;
    underbilled_items: Array<{ id: string; description: string; variance: number }>;
    underbilled_amount: number;
    contradictions: Array<{ id: string; title: string }>;
  };
  illustrative: {
    clinician_minutes_saved: number;
    revenue_at_risk: number;
    leakage_identified: number;
    note: string;
  };
  recent_audit: AuditEntry[];
};

export type AuditEntry = {
  id: string;
  actor_type: string;
  actor_name: string;
  action: string;
  entity_type: string;
  entity_id: string;
  patient_id?: string;
  before: any;
  after: any;
  meta: any;
  created_at: string;
};
