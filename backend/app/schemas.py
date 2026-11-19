from typing import Any, Literal

from pydantic import BaseModel, Field


class Claim(BaseModel):
    text: str
    source_event_ids: list[str] = Field(default_factory=list)
    source_segment_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.9
    human_authored: bool = False
    # Where a merged note took this item from: "recording" or "opd" (the signed OPD report).
    origin: str | None = None


class ExamFindings(BaseModel):
    general: Claim | None = None
    systemic: Claim | None = None


class MedicationMention(BaseModel):
    drug: str
    dose: str | None = None
    frequency: str | None = None
    source_event_ids: list[str] = Field(default_factory=list)
    source_segment_ids: list[str] = Field(default_factory=list)


class OpdHeader(BaseModel):
    """The record part of the OPD note: filled from registration and the visit, never from speech."""

    patient_name: str = ""
    age_sex: str = ""
    date_of_admission: str = ""
    hospital_number: str = ""
    department: str = ""
    unit_consultant: str = ""
    recorded_by: str = ""


# The hospital's OPD format, in its order. The first seven come from the record (OpdHeader);
# the rest are heard in the consultation.
OPD_HEARD_SECTIONS: list[tuple[str, str]] = [
    ("mode_of_admission", "Mode of admission"),
    ("referring_physician", "Referring physician"),
    ("previous_admission", "Previous admission"),
    ("previous_diagnosis", "Previous diagnosis"),
    ("allergies", "Allergies (food, drugs, other)"),
    ("pain", "Pain (site, duration, score, frequency, referral or radiation)"),
    ("occupation", "Occupation"),
    ("source_of_history", "Source of history and reliability"),
    ("chief_complaints", "Chief complaints"),
    ("history_of_present_illness", "History of present illness"),
]


class ConsultNote(BaseModel):
    # "opd_v2" is the hospital OPD format below; notes signed before it ("opd_v1") keep the old fields.
    format: str = "opd_v1"
    header: OpdHeader | None = None
    mode_of_admission: Claim | None = None
    referring_physician: Claim | None = None
    previous_admission: Claim | None = None
    previous_diagnosis: list[Claim] = Field(default_factory=list)
    allergies: list[Claim] = Field(default_factory=list)
    pain: Claim | None = None
    occupation: Claim | None = None
    source_of_history: Claim | None = None
    chief_complaints: list[Claim] = Field(default_factory=list)
    history_of_present_illness: Claim | None = None
    # Earlier format (opd_v1).
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


class AdmissionHeader(BaseModel):
    """Record part of the admission note: from registration and the visit, never from speech."""

    name: str = ""
    sex: str = ""
    age: str = ""
    op_number: str = ""
    date_of_admission: str = ""
    consultant: str = ""


# The hospital's admission format, in its order, after the record headings.
ADMISSION_HEARD_SECTIONS: list[tuple[str, str, bool]] = [
    ("admission_type", "Elective or emergency", False),
    ("ward", "Admit to ward", False),
    ("speciality", "Speciality", False),
    ("provisional_diagnosis", "Provisional diagnosis", True),
    ("proposed_treatment", "Proposed treatment", True),
    ("expected_outcome", "Expected outcome (improved, unchanged or worsened)", False),
    ("possible_complications", "Possible complications", True),
    ("allergies", "Allergies", True),
    ("cost_category", "Approximate cost or category", False),
    ("admission_labs", "Admission labs", True),
    ("imaging_studies", "Imaging studies", True),
    ("consultations_required", "Consultations required", True),
]


class AdmissionNote(BaseModel):
    # "admit_v2" is the hospital admission format; earlier notes ("admit_v1") keep the old fields.
    format: str = "admit_v1"
    header: AdmissionHeader | None = None
    admission_type: Claim | None = None
    ward: Claim | None = None
    speciality: Claim | None = None
    provisional_diagnosis: list[Claim] = Field(default_factory=list)
    proposed_treatment: list[Claim] = Field(default_factory=list)
    expected_outcome: Claim | None = None
    possible_complications: list[Claim] = Field(default_factory=list)
    allergies: list[Claim] = Field(default_factory=list)
    cost_category: Claim | None = None
    admission_labs: list[Claim] = Field(default_factory=list)
    imaging_studies: list[Claim] = Field(default_factory=list)
    consultations_required: list[Claim] = Field(default_factory=list)
    # Earlier format (admit_v1).
    chief_complaint: Claim | None = None
    history: Claim | None = None
    exam: ExamFindings = Field(default_factory=ExamFindings)
    assessment: list[Claim] = Field(default_factory=list)
    plan: list[Claim] = Field(default_factory=list)
    proposed_orders: list[dict[str, Any]] = Field(default_factory=list)
    allergies_to_verify: list[AllergyVerification] = Field(default_factory=list)
    not_documented: list[str] = Field(default_factory=list)


class ProposedTask(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    detail: str = ""
    priority: Literal["routine", "urgent", "critical"] = "routine"
    assignee_role: Literal["senior_doctor", "junior_doctor", "nurse"] = "junior_doctor"
    due_in_hours: int = Field(default=24, ge=1, le=168)
    source_segment_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.9


class WardRoundReport(BaseModel):
    findings: list[Claim] = Field(default_factory=list)
    assessment: list[Claim] = Field(default_factory=list)
    plan: list[Claim] = Field(default_factory=list)


class RoundDraft(BaseModel):
    note_claims: list[Claim] = Field(default_factory=list)
    report: WardRoundReport = Field(default_factory=WardRoundReport)
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
    specialty: str = ""
    specialist: str = ""
    question: Claim | None = None
    history: Claim | None = None
    urgency: Literal["routine", "urgent", "emergency"] = "routine"
    relevant_results: list[Claim] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    # Hospital referral form, part one (format "referral_v2"), dictated by the referring doctor.
    format: str | None = None
    header: dict[str, str] = Field(default_factory=dict)
    referral_type: Literal["immediate", "urgent", "routine"] | None = None
    unit_chief: Claim | None = None
    department: Claim | None = None
    salient_details: list[Claim] = Field(default_factory=list)
    not_documented: list[str] = Field(default_factory=list)
    needs_review: list[dict[str, str]] = Field(default_factory=list)


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
