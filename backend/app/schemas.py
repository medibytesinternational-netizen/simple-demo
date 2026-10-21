from typing import Any, Literal

from pydantic import BaseModel, Field


class Claim(BaseModel):
    text: str
    source_event_ids: list[str] = Field(default_factory=list)
    source_segment_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.9
    human_authored: bool = False


class ExamFindings(BaseModel):
    general: Claim | None = None
    systemic: Claim | None = None


class MedicationMention(BaseModel):
    drug: str
    dose: str | None = None
    frequency: str | None = None
    source_event_ids: list[str] = Field(default_factory=list)
    source_segment_ids: list[str] = Field(default_factory=list)


class ConsultNote(BaseModel):
    chief_complaint: Claim | None = None
    hpi: Claim | None = None
    exam: ExamFindings = Field(default_factory=ExamFindings)
    assessment: list[Claim] = Field(default_factory=list)
    plan: list[Claim] = Field(default_factory=list)
    medication_mentions: list[MedicationMention] = Field(default_factory=list)
    follow_up: Claim | None = None
    not_documented: list[str] = Field(default_factory=list)


class AllergyVerification(BaseModel):
    substance: str
    reaction: str = ""
    source_event_id: str = ""
    verified: bool = False


class AdmissionNote(BaseModel):
    chief_complaint: Claim | None = None
    history: Claim | None = None
    exam: ExamFindings = Field(default_factory=ExamFindings)
    assessment: list[Claim] = Field(default_factory=list)
    plan: list[Claim] = Field(default_factory=list)
    proposed_orders: list[dict[str, Any]] = Field(default_factory=list)
    allergies_to_verify: list[AllergyVerification] = Field(default_factory=list)
    not_documented: list[str] = Field(default_factory=list)


class ProposedTask(BaseModel):
    title: str
    detail: str = ""
    priority: Literal["routine", "urgent"] = "routine"
    due_in_hours: int = 24
    source_segment_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.9


class RoundDraft(BaseModel):
    note_claims: list[Claim] = Field(default_factory=list)
    nursing_entries: list[Claim] = Field(default_factory=list)
    proposed_tasks: list[ProposedTask] = Field(default_factory=list)
    not_documented: list[str] = Field(default_factory=list)


class ProgressNote(BaseModel):
    subjective: Claim | None = None
    objective: Claim | None = None
    exam: ExamFindings = Field(default_factory=ExamFindings)
    assessment: list[Claim] = Field(default_factory=list)
    plan: Claim | None = None
    not_documented: list[str] = Field(default_factory=list)


class ShiftSummary(BaseModel):
    shift_window: dict[str, str] = Field(default_factory=dict)
    vitals_summary: Claim | None = None
    meds_administered: list[Claim] = Field(default_factory=list)
    incidents: list[Claim] = Field(default_factory=list)
    concerns: list[Claim] = Field(default_factory=list)
    not_documented: list[str] = Field(default_factory=list)


class ICUEntry(BaseModel):
    category: Literal[
        "vitals", "ventilator", "infusion", "intake_output", "neuro", "lines", "skin", "medication", "other"
    ] = "other"
    label: str
    value: str
    unit: str = ""
    recorded_at: str = ""
    device: str = ""
    source_event_id: str = ""
    confidence: float = 0.95
    chart: Literal["icu", "ward"] = "icu"


class ICUFlowSheet(BaseModel):
    shift_window: dict[str, str] = Field(default_factory=dict)
    summary: Claim
    entries: list[ICUEntry] = Field(default_factory=list)
    not_documented: list[str] = Field(default_factory=list)


class InvestigationResult(BaseModel):
    name: str
    value: str
    flag: Literal["normal", "high", "low", "unknown"] = "unknown"
    event_id: str


class InvestigationReview(BaseModel):
    results: list[InvestigationResult] = Field(default_factory=list)
    trend_summary: Claim | None = None
    abnormal_summary: Claim | None = None
    pending: list[Claim] = Field(default_factory=list)
    not_documented: list[str] = Field(default_factory=list)


class DocumentRequestDraft(BaseModel):
    request_type: Literal["records", "pre_auth", "referral", "discharge_docs"] = "records"
    recipient: str = ""
    records_requested: list[str] = Field(default_factory=list)
    justification: Claim | None = None
    due_in_days: int = 5
    source_event_ids: list[str] = Field(default_factory=list)


class InvestigationRequestDraft(BaseModel):
    request_type: Literal["laboratory", "imaging"] = "laboratory"
    study: str
    indication: Claim
    diagnosis: str = ""
    allergies_to_verify: list[AllergyVerification] = Field(default_factory=list)
    priority: Literal["routine", "urgent", "stat"] = "routine"
    instructions: str = ""
    recipient: str = ""
    source_event_ids: list[str] = Field(default_factory=list)


class ReferralDraft(BaseModel):
    specialty: str
    specialist: str = ""
    question: Claim
    history: Claim
    urgency: Literal["routine", "urgent", "emergency"] = "routine"
    relevant_results: list[Claim] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)


class OcrField(BaseModel):
    name: str
    value: str
    unit: str = ""
    reference_range: str = ""
    collected_at: str = ""
    confidence: float = 0.9
    page: int = 1
    bbox: list[float] = Field(default_factory=list)


class OcrExtraction(BaseModel):
    document_type: str = "lab_report"
    fields: list[OcrField] = Field(default_factory=list)
    raw_text: str = ""


class DischargeSection(BaseModel):
    heading: str
    paragraphs: list[Claim] = Field(default_factory=list)


class DischargeMedication(BaseModel):
    drug: str
    dose: str = ""
    route: str = ""
    frequency: str = ""
    status: str = "continue"
    source_event_id: str = ""
    safety_status: Literal["ok", "review", "contraindicated"] = "ok"
    safety_note: str = ""


class DischargeSummary(BaseModel):
    sections: list[DischargeSection] = Field(default_factory=list)
    medications: list[DischargeMedication] = Field(default_factory=list)
    pending_results: list[Claim] = Field(default_factory=list)
    follow_up: list[Claim] = Field(default_factory=list)
    red_flags: list[Claim] = Field(default_factory=list)
    not_documented: list[str] = Field(default_factory=list)


class AlertCopy(BaseModel):
    title: str
    explanation: str
    recommended_action: str = ""
    severity: Literal["critical", "warning"] = "warning"


class ReconDiscrepancy(BaseModel):
    home_med: str
    current_order: str | None = None
    kind: Literal[
        "omitted",
        "dose_changed",
        "route_changed",
        "frequency_changed",
        "indication_missing",
        "duplicate",
        "interaction",
        "allergy",
        "contraindicated",
    ]
    field: str = ""
    home_value: str = ""
    current_value: str = ""
    explanation: str
    recommended_action: str = ""
    evidence_event_ids: list[str] = Field(default_factory=list)


class ReconExplanation(BaseModel):
    summary: str
    discrepancies: list[ReconDiscrepancy] = Field(default_factory=list)


class ClaimGap(BaseModel):
    kind: Literal[
        "missing_document",
        "unbilled_procedure",
        "underbilled_item",
        "unsupported_billing",
        "contradiction",
        "tpa_clarification",
    ]
    description: str
    evidence_event_ids: list[str] = Field(default_factory=list)


class ClaimGapExplanation(BaseModel):
    summary: str
    gaps: list[ClaimGap] = Field(default_factory=list)


class LeakageFinding(BaseModel):
    procedure: str
    billing_status: Literal["unbilled", "underbilled", "unsupported"]
    explanation: str
    evidence_event_ids: list[str] = Field(default_factory=list)


class LeakageExplanation(BaseModel):
    summary: str
    findings: list[LeakageFinding] = Field(default_factory=list)


FEATURE_MODELS: dict[str, type[BaseModel]] = {
    "F1": ConsultNote,
    "F2": AdmissionNote,
    "F3": RoundDraft,
    "F4": ProgressNote,
    "F5": AlertCopy,
    "F6": ReconExplanation,
    "F7": ICUFlowSheet,
    "F9": DischargeSummary,
    "F10": InvestigationRequestDraft,
    "F11": ReferralDraft,
    "F12": ClaimGapExplanation,
    "F13": LeakageExplanation,
}

OUTPUT_SCHEMAS = {key: model.model_json_schema() for key, model in FEATURE_MODELS.items()}
