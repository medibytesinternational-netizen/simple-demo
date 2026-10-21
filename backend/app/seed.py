from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from . import clock
from .config import settings
from .models import (
    Alert,
    AuditEntry,
    BillLineItem,
    ClaimReview,
    Document,
    DocumentRequest,
    Draft,
    Encounter,
    InvestigationRequest,
    LLMCall,
    Patient,
    Referral,
    Task,
    TimelineEvent,
)
from .services.ocr import seed_extraction
from .services.rules import evaluate_rules
from .services.timeline import add_audit, get_state

DEMO_NOW = settings.demo_now
ADMISSION = datetime(2026, 10, 18, 14, 10, 0)


def _clear(db: Session) -> None:
    for model in (
        AuditEntry,
        LLMCall,
        ClaimReview,
        BillLineItem,
        InvestigationRequest,
        Referral,
        DocumentRequest,
        Document,
        Alert,
        Task,
        Draft,
        TimelineEvent,
        Encounter,
        Patient,
    ):
        db.execute(delete(model))
    db.commit()


def _event(
    db: Session,
    event_id: str,
    *,
    type: str,
    title: str,
    occurred_at: datetime,
    body_text: str = "",
    payload: dict | None = None,
    source: str = "seed",
    author_type: str = "human",
    author_name: str = "Dr. Meera Shah",
    subtype: str | None = None,
    confidence: float | None = None,
    document_id: str | None = None,
    encounter_id: str = "enc_ipd_1",
) -> TimelineEvent:
    event = TimelineEvent(
        id=event_id,
        patient_id="pat_ravi",
        encounter_id=encounter_id,
        type=type,
        subtype=subtype,
        title=title,
        body_text=body_text,
        payload=payload or {},
        source=source,
        author_type=author_type,
        author_name=author_name,
        status="approved",
        confidence=confidence,
        occurred_at=occurred_at,
        created_at=occurred_at,
        approved_by=author_name,
        approved_at=occurred_at,
        document_id=document_id,
    )
    db.add(event)
    return event


def _med(
    db: Session,
    event_id: str,
    drug: str,
    dose: str,
    frequency: str,
    *,
    kind: str,
    indication: str,
    occurred_at: datetime,
    route: str = "PO",
    status: str = "active",
) -> None:
    _event(
        db,
        event_id,
        type="med_order",
        title=f"{'Home' if kind == 'home' else 'Inpatient'} medication — {drug} {dose} {frequency}",
        occurred_at=occurred_at,
        body_text=f"{drug} {dose} {frequency} {route} ({kind}, {status})",
        payload={
            "drug": drug,
            "dose": dose,
            "route": route,
            "frequency": frequency,
            "kind": kind,
            "status": status,
            "indication": indication,
        },
        source="seed",
        subtype="home" if kind == "home" else "inpatient",
    )


def seed_rehearsal(db: Session) -> None:
    patient = Patient(
        id="pat_ravi",
        mrn="MB-1001",
        name="Ravi Menon",
        age=58,
        sex="Male",
        allergies=["Penicillin — rash"],
        problems=["Type 2 diabetes", "Hypertension", "CKD stage 3b", "Atrial fibrillation"],
        weight_kg=82,
        height_cm=172,
        code_status="Full code",
    )
    encounter = Encounter(
        id="enc_ipd_1",
        patient_id=patient.id,
        kind="IPD",
        ward="Ward 4B",
        bed="Bed 12",
        attending="Dr. Meera Shah",
        admitted_at=ADMISSION,
        status="active",
    )
    db.add_all([patient, encounter])
    icu_encounter = Encounter(
        id="enc_icu_1",
        patient_id=patient.id,
        kind="ICU",
        ward="ICU",
        bed="ICU-3",
        attending="Dr. Meera Shah",
        admitted_at=datetime(2026, 10, 18, 15, 0),
        discharged_at=datetime(2026, 10, 19, 8, 0),
        status="closed",
    )
    db.add(icu_encounter)
    db.flush()

    # --- OPD and admission -------------------------------------------------
    _event(
        db,
        "evt_seed_consult",
        type="consult_note",
        subtype="f1",
        title="OPD consultation — right leg cellulitis",
        occurred_at=datetime(2026, 10, 16, 10, 20),
        body_text=(
            "Chief complaint: right leg swelling and redness for four days.\n"
            "History: progressive pain, warmth and fever. Denies chest pain or breathlessness.\n"
            "Examination: temperature 38.1°C, pulse 96, BP 138/86, SpO2 96%. "
            "Right lower leg erythematous, warm and tender with demarcation; no ulcer.\n"
            "Assessment: right lower leg cellulitis; type 2 diabetes; CKD stage 3b.\n"
            "Plan: admit for IV antibiotics, check creatinine and potassium, hold metformin."
        ),
        payload={
            "chief_complaint": "Right leg swelling, redness and pain for four days.",
            "assessment": ["Right lower leg cellulitis", "Type 2 diabetes", "CKD stage 3b"],
            "plan": ["Admit for IV antibiotics", "Check renal function and potassium", "Hold metformin"],
        },
        source="F1",
        author_type="model",
        confidence=0.94,
    )
    _event(
        db,
        "evt_seed_admission",
        type="admission_note",
        subtype="f2",
        title="Admission assessment",
        occurred_at=ADMISSION,
        body_text=(
            "Admitted with right lower leg cellulitis. Background of type 2 diabetes, hypertension, "
            "CKD stage 3b and atrial fibrillation. Penicillin allergy documented. "
            "Plan: IV antibiotics, renal monitoring, daily wound review."
        ),
        payload={
            "chief_complaint": "Right lower leg cellulitis",
            "assessment": ["Right lower leg cellulitis", "CKD stage 3b"],
            "plan": ["IV antibiotics", "Renal monitoring", "Daily wound review"],
        },
        source="F2",
        author_type="model",
        confidence=0.93,
    )

    # --- Observations and labs ---------------------------------------------
    _event(
        db,
        "evt_seed_vitals",
        type="vitals",
        title="Overnight observations",
        occurred_at=datetime(2026, 10, 20, 6, 0),
        body_text="Temp 37.4°C, HR 88, BP 132/84, RR 18, SpO2 97% on room air.",
        payload={
            "temperature_c": 37.4,
            "heart_rate": 88,
            "systolic": 132,
            "diastolic": 84,
            "respiratory_rate": 18,
            "spo2": 97,
            "recorded_at": "2026-10-20T06:00:00",
        },
    )
    _event(
        db,
        "evt_seed_allergy",
        type="allergy_record",
        title="Allergy record — penicillin",
        occurred_at=datetime(2026, 10, 18, 14, 5),
        body_text="Penicillin allergy documented: rash. Verify before prescribing a penicillin-class antibiotic.",
        payload={"substance": "Penicillin", "reaction": "rash", "verified": True},
        source="patient_record",
        author_type="human",
        author_name="Admissions clerk",
    )
    _event(
        db,
        "evt_seed_nursing_contradiction",
        type="nursing_note",
        title="Nursing admission note — allergy history",
        occurred_at=datetime(2026, 10, 18, 15, 30),
        body_text="Patient reports no known drug allergies. No allergy bracelet seen at this assessment.",
        payload={"allergies": [], "assertion": "no_known_allergies"},
        source="nursing",
        author_type="human",
        author_name="Nurse Anita Rao",
    )
    icu_readings = [
        ("evt_icu_temp_1", "vitals", "Temperature", "38.6", "°C", "2026-10-18T16:00:00", "Bedside monitor", "high"),
        ("evt_icu_hr_1", "vitals", "Heart rate", "112", "bpm", "2026-10-18T16:00:00", "Bedside monitor", "high"),
        ("evt_icu_bp_1", "vitals", "Blood pressure", "96/58", "mmHg", "2026-10-18T16:00:00", "Bedside monitor", "low"),
        ("evt_icu_spo2_1", "vitals", "SpO2", "94", "%", "2026-10-18T16:00:00", "Bedside monitor", "low"),
        ("evt_icu_urine_1", "intake_output", "Urine output", "18", "mL/hour", "2026-10-18T18:00:00", "Urine meter", "low"),
        ("evt_icu_infusion_1", "infusion", "Flucloxacillin infusion", "1", "g", "2026-10-18T18:00:00", "Infusion pump", "normal"),
        ("evt_icu_neuro_1", "neuro", "GCS", "15", "/15", "2026-10-18T20:00:00", "Nursing chart", "normal"),
        ("evt_icu_line_1", "lines", "Peripheral IV", "Right forearm", "", "2026-10-18T16:10:00", "Nursing chart", "normal"),
        ("evt_icu_temp_2", "vitals", "Temperature", "37.8", "°C", "2026-10-19T06:00:00", "Bedside monitor", "normal"),
        ("evt_icu_urine_2", "intake_output", "Urine output", "32", "mL/hour", "2026-10-19T06:00:00", "Urine meter", "normal"),
    ]
    for event_id, category, label, value, unit, recorded_at, device, flag in icu_readings:
        _event(
            db,
            event_id,
            type="device_reading",
            title=f"{label} — {value} {unit}".strip(),
            occurred_at=datetime.fromisoformat(recorded_at),
            body_text=f"{label}: {value} {unit} from {device}.",
            payload={
                "category": category,
                "label": label,
                "value": value,
                "unit": unit,
                "recorded_at": recorded_at,
                "device": device,
                "flag": flag,
            },
            source="device",
            author_type="device",
            author_name=device,
            confidence=0.99,
            encounter_id="enc_icu_1",
        )

    labs = [
        ("evt_seed_lab_creatinine", "Creatinine", 2.9, "mg/dL", "0.7 - 1.3", "high", "unreviewed", "2026-10-19T06:00:00"),
        ("evt_seed_lab_egfr", "eGFR", 22, "mL/min/1.73m²", "> 90", "low", "reviewed", "2026-10-19T06:00:00"),
        ("evt_seed_lab_potassium", "Potassium", 5.1, "mmol/L", "3.5 - 5.1", "high", "reviewed", "2026-10-19T06:00:00"),
        ("evt_seed_lab_hba1c", "HbA1c", 8.4, "%", "4.0 - 5.6", "high", "reviewed", "2026-10-18T16:00:00"),
        ("evt_seed_lab_wbc", "White cell count", 13.8, "10^3/µL", "4.0 - 11.0", "high", "reviewed", "2026-10-19T06:00:00"),
        ("evt_seed_lab_crp", "CRP", 92, "mg/L", "0 - 5", "high", "reviewed", "2026-10-19T06:00:00"),
    ]
    for event_id, name, value, unit, reference, flag, review, collected in labs:
        _event(
            db,
            event_id,
            type="lab_result",
            title=f"{name} — {value} {unit}",
            occurred_at=datetime.fromisoformat(collected),
            body_text=f"{name}: {value} {unit} (reference {reference}); flag {flag}; {review}.",
            payload={
                "name": name,
                "value": value,
                "unit": unit,
                "reference_range": reference,
                "flag": flag,
                "review_status": review,
                "collected_at": collected,
            },
            source="lab",
            author_type="human",
            author_name="Laboratory",
        )

    # --- Medications -------------------------------------------------------
    _med(db, "evt_seed_med_metformin_home", "Metformin", "1 g", "BD", kind="home",
         indication="Type 2 diabetes", occurred_at=datetime(2026, 9, 1, 8, 0))
    _med(db, "evt_seed_med_amlodipine_home", "Amlodipine", "10 mg", "OD", kind="home",
         indication="Hypertension", occurred_at=datetime(2026, 9, 1, 8, 0))
    _med(db, "evt_seed_med_atorvastatin_home", "Atorvastatin", "20 mg", "ON", kind="home",
         indication="Cardiovascular risk", occurred_at=datetime(2026, 9, 1, 20, 0))
    _med(db, "evt_seed_med_warfarin_home", "Warfarin", "5 mg", "OD", kind="home",
         indication="Atrial fibrillation", occurred_at=datetime(2026, 9, 1, 18, 0))
    _med(db, "evt_seed_med_ibuprofen_home", "Ibuprofen", "400 mg", "PRN", kind="home",
         indication="Knee pain", occurred_at=datetime(2026, 9, 1, 8, 0))

    _med(db, "evt_seed_med_metformin", "Metformin", "1 g", "BD", kind="inpatient",
         indication="Type 2 diabetes", occurred_at=datetime(2026, 10, 18, 16, 0))
    _med(db, "evt_seed_med_amlodipine", "Amlodipine", "10 mg", "OD", kind="inpatient",
         indication="Hypertension", occurred_at=datetime(2026, 10, 18, 16, 0))
    _med(db, "evt_seed_med_warfarin", "Warfarin", "5 mg", "OD", kind="inpatient",
         indication="Atrial fibrillation", occurred_at=datetime(2026, 10, 18, 16, 0))
    _med(db, "evt_seed_med_ibuprofen", "Ibuprofen", "400 mg", "PRN", kind="inpatient",
         indication="Knee pain", occurred_at=datetime(2026, 10, 18, 16, 0))
    _med(db, "evt_seed_med_flucloxacillin", "Flucloxacillin", "1 g", "QDS", kind="inpatient",
         indication="Cellulitis", occurred_at=datetime(2026, 10, 18, 17, 0), route="IV")

    # --- Notes -------------------------------------------------------------
    _event(
        db,
        "evt_seed_nursing",
        type="nursing_note",
        title="Nursing shift note — night",
        occurred_at=datetime(2026, 10, 20, 6, 30),
        body_text="Afebrile overnight after paracetamol. Slept poorly. No falls. Leg pain improved.",
        payload={"shift": "night", "temperature_c": 37.4},
    )
    _event(
        db,
        "evt_seed_round",
        type="round_note",
        subtype="f3",
        title="Ward round — day 2",
        occurred_at=datetime(2026, 10, 19, 8, 30),
        body_text=(
            "Continue IV flucloxacillin and review the leg tomorrow. Check potassium and renal function. "
            "Stop metformin until renal function improves. Increase ibuprofen for knee pain was not accepted."
        ),
        payload={
            "note_claims": [
                "Continue IV antibiotics and review the leg tomorrow.",
                "Check potassium and renal function.",
                "Hold metformin until renal function improves.",
            ],
            "proposed_tasks": [
                "Continue IV flucloxacillin and review the leg",
                "Check potassium and renal function",
                "Stop metformin",
                "Increase ibuprofen for knee pain",
            ],
            "plan_actions": [
                {
                    "action": "hold",
                    "drug": "Metformin",
                    "status": "open",
                    "due_at": "2026-10-19T12:30:00",
                }
            ],
        },
        source="F3",
        author_type="model",
        confidence=0.92,
    )
    _event(
        db,
        "evt_seed_progress",
        type="progress_note",
        subtype="f4",
        title="Daily progress note — day 2",
        occurred_at=datetime(2026, 10, 19, 17, 0),
        body_text="Patient reports less leg pain. Temperature settled. Examination and plan to be completed on ward round.",
        payload={"subjective": "Less leg pain, no breathlessness.", "not_documented": ["Examination", "Plan"]},
        source="F4",
        author_type="model",
        confidence=0.86,
    )
    _event(
        db,
        "evt_seed_procedure",
        type="procedure",
        title="Wound debridement — right lower leg",
        occurred_at=datetime(2026, 10, 19, 11, 30),
        body_text="Bedside wound debridement of right lower leg cellulitis performed by surgical team.",
        payload={"procedure": "Wound debridement", "code": "97597", "performed_by": "Surgical team"},
        source="procedure",
        author_type="human",
        author_name="Dr. A. Nair",
    )

    # --- Document + bill ---------------------------------------------------
    document = Document(
        id="doc_seed_outside",
        patient_id=patient.id,
        encounter_id=encounter.id,
        filename="outside_creatinine_12oct.svg",
        mime="image/svg+xml",
        path="",
        image_kind="svg",
        doc_type="lab_report",
        ocr_status="needs_confirmation",
        raw_text=seed_extraction()["raw_text"],
        extracted=seed_extraction(),
        uploaded_by=settings.demo_user,
        uploaded_at=datetime(2026, 10, 19, 15, 10),
    )
    db.add(document)

    db.add(
        DocumentRequest(
            id="req_seed_preauth",
            patient_id=patient.id,
            encounter_id=encounter.id,
            request_type="pre_auth",
            records_requested=["Pre-authorization approval letter"],
            recipient="Star Health — Provider Desk",
            justification="Required before the claim pack can enter review for the current admission.",
            due_at=datetime(2026, 10, 19, 17, 0),
            status="overdue",
            created_at=datetime(2026, 10, 18, 17, 30),
            approved_by=settings.demo_user,
        )
    )
    _event(
        db,
        "evt_seed_document_request",
        type="document_request",
        title="Outbound request — pre-authorization",
        occurred_at=datetime(2026, 10, 18, 17, 30),
        body_text="Request for pre-authorization approval letter sent to Star Health (demo only).",
        payload={"request_id": "req_seed_preauth", "status": "overdue", "records": ["Pre-authorization approval letter"]},
        source="F10",
        author_type="model",
        confidence=0.9,
    )

    db.add(
        InvestigationRequest(
            id="inv_seed_renal",
            patient_id=patient.id,
            encounter_id=encounter.id,
            request_type="imaging",
            study="Renal ultrasound with Doppler",
            indication="CKD stage 3b with eGFR 22 and creatinine 2.9 mg/dL; assess renal parenchyma and obstruction.",
            diagnosis="CKD stage 3b; right lower leg cellulitis",
            allergies_to_verify=[
                {"substance": "Penicillin", "reaction": "rash", "source_event_id": "evt_seed_allergy", "verified": False}
            ],
            priority="routine",
            instructions="Assess renal size, echogenicity, hydronephrosis and renal artery flow. No contrast unless reviewed.",
            status="approved",
            approved_by=settings.demo_user,
            created_at=datetime(2026, 10, 20, 7, 30),
        )
    )
    db.add(
        Referral(
            id="ref_seed_neph",
            patient_id=patient.id,
            encounter_id=encounter.id,
            specialty="Nephrology",
            specialist="Nephrology on-call service",
            question="Does this patient with CKD stage 3b and eGFR 22 need nephrology co-management or dialysis planning during this admission?",
            history="Type 2 diabetes, hypertension and CKD stage 3b; admitted with cellulitis and impaired renal function.",
            urgency="urgent",
            status="sent",
            approved_by=settings.demo_user,
            sent_at=datetime(2026, 10, 20, 8, 0),
            created_at=datetime(2026, 10, 20, 8, 0),
        )
    )

    bill_items = [
        ("bill_room", "Room charge — 2 nights", "ROOM2", 8000, 8000, ["evt_seed_admission"]),
        ("bill_antibiotics", "IV antibiotics", "J01", 3200, 4200, ["evt_seed_round"]),
        ("bill_nursing", "Nursing care", "NURSE", 1500, 1500, ["evt_seed_nursing"]),
        ("bill_physio", "Physiotherapy session", "PT01", 1200, 2400, []),
    ]
    for item_id, description, code, amount, expected_amount, docs in bill_items:
        db.add(
            BillLineItem(
                id=item_id,
                patient_id=patient.id,
                encounter_id=encounter.id,
                code=code,
                description=description,
                amount=amount,
                expected_amount=expected_amount,
                billed_at=datetime(2026, 10, 20, 7, 0),
                documentation_event_ids=docs,
            )
        )
    _event(
        db,
        "evt_seed_billing",
        type="billing",
        title="Seeded bill — 4 line items",
        occurred_at=datetime(2026, 10, 20, 7, 0),
        body_text="Seeded bill total INR 13,900 across room, antibiotics, nursing and physiotherapy.",
        payload={
            "total_amount": 13900,
            "line_items": [
                {"description": "Room charge — 2 nights", "amount": 8000},
                {"description": "IV antibiotics", "amount": 3200},
                {"description": "Nursing care", "amount": 1500},
                {"description": "Physiotherapy session", "amount": 1200},
            ],
        },
        source="billing",
        author_type="system",
        author_name="Billing system (seeded)",
    )

    # --- Tasks -------------------------------------------------------------
    tasks = [
        ("tsk_seed_metformin", "Stop metformin and document the rationale", "critical", "accepted",
         DEMO_NOW - timedelta(hours=2), "evt_seed_round"),
        ("tsk_seed_potassium", "Check potassium and renal function", "urgent", "accepted",
         DEMO_NOW + timedelta(hours=4), "evt_seed_round"),
        ("tsk_seed_antibiotics", "Continue IV flucloxacillin and review the leg tomorrow", "routine", "completed",
         DEMO_NOW - timedelta(hours=1), "evt_seed_round"),
        ("tsk_seed_followup", "Book medical outpatient follow-up in two weeks", "routine", "proposed",
         DEMO_NOW + timedelta(days=2), None),
    ]
    for task_id, title, priority, status, due, source in tasks:
        assigned_to = "Nurse Anita Rao" if task_id in {"tsk_seed_metformin", "tsk_seed_potassium"} else settings.demo_user
        db.add(
            Task(
                id=task_id,
                patient_id=patient.id,
                encounter_id=encounter.id,
                title=title,
                detail="Seeded task for the full inpatient demo.",
                status=status,
                priority=priority,
                due_at=due,
                owner=assigned_to,
                assigned_to=assigned_to,
                assigned_at=datetime(2026, 10, 19, 9, 5),
                assigned_by=settings.demo_user,
                acknowledged_at=datetime(2026, 10, 19, 9, 10)
                if task_id in {"tsk_seed_metformin", "tsk_seed_potassium", "tsk_seed_antibiotics"}
                else None,
                acknowledged_by=assigned_to
                if task_id in {"tsk_seed_metformin", "tsk_seed_potassium", "tsk_seed_antibiotics"}
                else None,
                escalation_level=1 if task_id == "tsk_seed_metformin" else 0,
                escalated_at=DEMO_NOW - timedelta(hours=1) if task_id == "tsk_seed_metformin" else None,
                escalation_reason="Overdue critical task" if task_id == "tsk_seed_metformin" else None,
                source_event_id=source,
                created_by=settings.demo_user,
                completed_at=DEMO_NOW - timedelta(hours=3) if status == "completed" else None,
                created_at=datetime(2026, 10, 19, 9, 0),
            )
        )

    # --- Small hospital cohort for the F14 aggregate view -------------------
    cohort = [
        {
            "patient": Patient(
                id="pat_anita",
                mrn="MB-2042",
                name="Anita Desai",
                age=67,
                sex="Female",
                allergies=["Sulfonamides — rash"],
                problems=["Heart failure", "Atrial fibrillation"],
                weight_kg=68,
                height_cm=158,
                code_status="Full code",
            ),
            "encounter": Encounter(
                id="enc_ward_2",
                patient_id="pat_anita",
                kind="IPD",
                ward="Ward 4",
                bed="4B",
                attending="Dr. Meera Shah",
                admitted_at=datetime(2026, 10, 19, 10, 30),
                status="active",
            ),
            "task": {
                "id": "tsk_cohort_anita",
                "title": "Review ACE inhibitor dose and renal function",
                "priority": "urgent",
                "status": "accepted",
                "due_at": DEMO_NOW - timedelta(hours=3),
                "assigned_to": "Nurse Anita Rao",
            },
            "alert": {
                "id": "alr_cohort_anita",
                "severity": "warning",
                "title": "Unreviewed potassium result",
                "explanation": "Potassium 5.6 mmol/L remains unreviewed on Ward 4.",
            },
        },
        {
            "patient": Patient(
                id="pat_joseph",
                mrn="MB-2051",
                name="Joseph Fernandes",
                age=72,
                sex="Male",
                allergies=[],
                problems=["COPD", "CKD stage 2"],
                weight_kg=74,
                height_cm=170,
                code_status="Full code",
            ),
            "encounter": Encounter(
                id="enc_ward_3",
                patient_id="pat_joseph",
                kind="IPD",
                ward="Ward 5",
                bed="5A",
                attending="Dr. Arjun Rao",
                admitted_at=datetime(2026, 10, 19, 14, 0),
                status="active",
            ),
            "task": {
                "id": "tsk_cohort_joseph",
                "title": "Repeat ABG after oxygen change",
                "priority": "critical",
                "status": "accepted",
                "due_at": DEMO_NOW - timedelta(hours=1),
                "assigned_to": "Dr. Meera Shah",
            },
            "alert": {
                "id": "alr_cohort_joseph",
                "severity": "critical",
                "title": "Escalating oxygen requirement",
                "explanation": "Oxygen requirement increased from 2 L to 6 L/min in the last four hours.",
            },
        },
        {
            "patient": Patient(
                id="pat_meera",
                mrn="MB-2060",
                name="Meera Iyer",
                age=45,
                sex="Female",
                allergies=["Latex — contact dermatitis"],
                problems=["Post-operative day 1"],
                weight_kg=61,
                height_cm=163,
                code_status="Full code",
            ),
            "encounter": Encounter(
                id="enc_day_1",
                patient_id="pat_meera",
                kind="Day care",
                ward="Day Care",
                bed="DC-2",
                attending="Dr. Kavita Menon",
                admitted_at=datetime(2026, 10, 20, 7, 30),
                status="active",
            ),
            "task": {
                "id": "tsk_cohort_meera",
                "title": "Confirm discharge medication list",
                "priority": "routine",
                "status": "in_progress",
                "due_at": DEMO_NOW + timedelta(hours=2),
                "assigned_to": "Pharmacist Dev Patel",
            },
            "alert": None,
        },
        {
            "patient": Patient(
                id="pat_arun",
                mrn="MB-1988",
                name="Arun Pillai",
                age=55,
                sex="Male",
                allergies=[],
                problems=["Community-acquired pneumonia"],
                weight_kg=78,
                height_cm=175,
                code_status="Full code",
            ),
            "encounter": Encounter(
                id="enc_ward_4",
                patient_id="pat_arun",
                kind="IPD",
                ward="Ward 4",
                bed="4A",
                attending="Dr. Arjun Rao",
                admitted_at=datetime(2026, 10, 16, 9, 0),
                discharged_at=datetime(2026, 10, 20, 8, 0),
                status="discharged",
            ),
            "task": {
                "id": "tsk_cohort_arun",
                "title": "Send discharge summary to GP",
                "priority": "routine",
                "status": "completed",
                "due_at": DEMO_NOW - timedelta(hours=4),
                "assigned_to": "Dr. Meera Shah",
            },
            "alert": None,
        },
    ]
    for row in cohort:
        db.add_all([row["patient"], row["encounter"]])
        task = row["task"]
        db.add(
            Task(
                id=task["id"],
                patient_id=row["patient"].id,
                encounter_id=row["encounter"].id,
                title=task["title"],
                detail="Seeded hospital-cohort task for the F14 aggregate view.",
                status=task["status"],
                priority=task["priority"],
                due_at=task["due_at"],
                owner=task["assigned_to"],
                assigned_to=task["assigned_to"],
                assigned_at=datetime(2026, 10, 20, 8, 0),
                assigned_by=settings.demo_user,
                acknowledged_at=datetime(2026, 10, 20, 8, 5)
                if task["status"] in {"accepted", "in_progress", "completed"}
                else None,
                acknowledged_by=task["assigned_to"]
                if task["status"] in {"accepted", "in_progress", "completed"}
                else None,
                escalation_level=1
                if task["status"] == "accepted" and task["due_at"] < DEMO_NOW
                else 0,
                escalated_at=DEMO_NOW - timedelta(minutes=30)
                if task["status"] == "accepted" and task["due_at"] < DEMO_NOW
                else None,
                escalation_reason="Overdue in the hospital queue"
                if task["status"] == "accepted" and task["due_at"] < DEMO_NOW
                else None,
                created_by=settings.demo_user,
                completed_at=DEMO_NOW - timedelta(hours=2)
                if task["status"] == "completed"
                else None,
                created_at=datetime(2026, 10, 19, 9, 0),
            )
        )
        alert = row["alert"]
        if alert:
            db.add(
                Alert(
                    id=alert["id"],
                    patient_id=row["patient"].id,
                    encounter_id=row["encounter"].id,
                    rule_id="COHORT",
                    dedupe_key=alert["id"],
                    severity=alert["severity"],
                    title=alert["title"],
                    explanation=alert["explanation"],
                    recommended_action="Review and document the clinical response.",
                    evidence_event_ids=[],
                    status="open",
                    created_at=datetime(2026, 10, 20, 8, 30),
                )
            )

    db.flush()

    # Every seeded event gets an audit trail entry so the audit drawer is never empty.
    seeded_events = db.query(TimelineEvent).filter(TimelineEvent.patient_id == patient.id).all()
    for event in seeded_events:
        add_audit(
            db,
            "timeline_committed",
            "timeline_event",
            event.id,
            patient.id,
            actor_type="system",
            actor_name="Demo seed",
            after={"type": event.type, "title": event.title, "source": event.source},
            meta={"seeded": True},
        )

    db.commit()

    state = get_state(db, patient, encounter)
    evaluate_rules(db, patient, encounter, state)
    db.commit()

    add_audit(
        db,
        "demo_reset",
        "demo",
        "rehearsal",
        patient.id,
        actor_type="system",
        actor_name="Demo control",
        after={"mode": "rehearsal", "events": len(seeded_events)},
    )
    db.commit()


def seed_start(db: Session) -> None:
    patient = Patient(
        id="pat_ravi",
        mrn="MB-1001",
        name="Ravi Menon",
        age=58,
        sex="Male",
        allergies=["Penicillin — rash"],
        problems=["Type 2 diabetes", "Hypertension", "CKD stage 3b", "Atrial fibrillation"],
        weight_kg=82,
        height_cm=172,
        code_status="Full code",
    )
    encounter = Encounter(
        id="enc_ipd_1",
        patient_id=patient.id,
        kind="IPD",
        ward="Ward 4B",
        bed="Bed 12",
        attending="Dr. Meera Shah",
        admitted_at=DEMO_NOW,
        status="active",
    )
    db.add_all([patient, encounter])
    add_audit(
        db,
        "demo_reset",
        "demo",
        "start",
        patient.id,
        actor_type="system",
        actor_name="Demo control",
        after={"mode": "start", "events": 0},
    )
    db.commit()


def reset_demo(db: Session, mode: str = "rehearsal") -> None:
    clock.reset()
    _clear(db)
    if mode == "start":
        seed_start(db)
    else:
        seed_rehearsal(db)


def ensure_seed(db: Session) -> None:
    patient = db.get(Patient, "pat_ravi")
    if patient:
        return
    reset_demo(db, "rehearsal")
