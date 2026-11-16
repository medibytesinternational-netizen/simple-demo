from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .services.identity import acting_name
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
from .models_ext import RESETTABLE
from .seeds import run_hooks
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
    for model in RESETTABLE:
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
        uploaded_by=acting_name(),
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
            approved_by=acting_name(),
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
            approved_by=acting_name(),
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
            approved_by=acting_name(),
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
        assigned_to = "Nurse Anita Rao" if task_id in {"tsk_seed_metformin", "tsk_seed_potassium"} else acting_name()
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
                assignee_role="nurse" if assigned_to.startswith("Nurse") else None,
                category="lab" if task_id == "tsk_seed_potassium" else "general",
                assigned_at=datetime(2026, 10, 19, 9, 5),
                assigned_by=acting_name(),
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
                created_by=acting_name(),
                completed_at=DEMO_NOW - timedelta(hours=3) if status == "completed" else None,
                created_at=datetime(2026, 10, 19, 9, 0),
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
    run_hooks(db, mode)
    db.commit()


# Patients the old rehearsal seed created for the dashboard. They are no longer seeded; a database
# made before that change still holds them, so startup removes them and everything that is theirs.
LEGACY_COHORT_IDS = ("pat_anita", "pat_joseph", "pat_meera", "pat_arun")


def purge_legacy_cohort(db: Session) -> int:
    """Delete the old cohort patients and every row that belongs to them. Returns patients removed."""
    from .db import Base

    present = [pid for pid in LEGACY_COHORT_IDS if db.get(Patient, pid)]
    if not present:
        return 0
    for table in Base.metadata.sorted_tables:
        if "patient_id" in table.c:
            db.execute(delete(table).where(table.c.patient_id.in_(present)))
    db.execute(delete(Patient).where(Patient.id.in_(present)))
    db.commit()
    return len(present)


def latest_recorded_time(db: Session) -> datetime | None:
    """The newest time anything was recorded, so the clock can carry on from it after a restart."""

    candidates = [
        db.scalar(select_max(TimelineEvent.created_at)),
        db.scalar(select_max(TimelineEvent.occurred_at)),
        db.scalar(select_max(Draft.created_at)),
        db.scalar(select_max(AuditEntry.created_at)),
        db.scalar(select_max(Document.uploaded_at)),
        db.scalar(select_max(Task.created_at)),
    ]
    found = [c for c in candidates if c]
    return max(found) if found else None


def select_max(column):
    from sqlalchemy import func, select

    return select(func.max(column))


def repair_event_order(db: Session) -> int:
    """Re-time entries that a clock restart stamped earlier than entries saved before them.

    Only entries the running app timed "now" (occurred_at within a second of created_at, with
    sub-second precision) are moved, and only forward, to just after the app entry before them.
    Seeded history is never touched. Dated entries (a lab's collection
    date, a report's date) keep their date. Uses SQLite's insertion order. Returns entries moved.
    """
    from datetime import timedelta

    from sqlalchemy import text

    if db.get_bind().dialect.name != "sqlite":
        return 0
    rows = db.execute(text(
        "SELECT id, patient_id, occurred_at, created_at FROM timeline_events ORDER BY patient_id, rowid"
    )).all()
    moved = 0
    latest: dict[str, datetime] = {}
    for event_id, patient_id, occurred, created in rows:
        occurred = datetime.fromisoformat(str(occurred))
        created = datetime.fromisoformat(str(created))
        # Timed "now" by the running app: occurred and saved together, with sub-second precision.
        # Seeded entries carry their clinical time on whole minutes and are never moved.
        auto = abs((created - occurred).total_seconds()) <= 1 and created.microsecond != 0
        floor = latest.get(patient_id)
        if auto and floor and created <= floor:
            new_time = floor + timedelta(milliseconds=1)
            db.execute(text("UPDATE timeline_events SET occurred_at = :t, created_at = :t WHERE id = :id"),
                       {"t": new_time, "id": event_id})
            created = new_time
            moved += 1
        if auto:
            latest[patient_id] = max(created, floor) if floor else created
    if moved:
        db.commit()
    return moved


def purge_patients_except(db: Session, keep: set[str]) -> list[str]:
    """Delete every patient not in ``keep`` and every row and stored file that belongs to them.

    Files: their documents' stored files (uploads, signed notes) and the intake files attached to
    them or never attached. Returns the ids removed.
    """
    import shutil
    from pathlib import Path

    from .db import Base

    gone = [pid for (pid,) in db.query(Patient.id).all() if pid not in keep]
    if not gone:
        return []
    for document in db.query(Document).filter(Document.patient_id.in_(gone)).all():
        path = Path(document.path or "")
        if path.is_file() and settings.uploads_dir in path.resolve().parents:
            path.unlink(missing_ok=True)
    intake_root = settings.uploads_dir / "intake"
    if intake_root.is_dir():
        import json

        for folder in intake_root.iterdir():
            meta = folder / "meta.json"
            try:
                attached = json.loads(meta.read_text(encoding="utf-8")).get("attached_to") if meta.is_file() else None
            except ValueError:
                attached = None
            if attached is None or attached in gone:
                shutil.rmtree(folder, ignore_errors=True)
    for table in Base.metadata.sorted_tables:
        if "patient_id" in table.c:
            db.execute(delete(table).where(table.c.patient_id.in_(gone)))
    db.execute(delete(Patient).where(Patient.id.in_(gone)))
    db.commit()
    return gone


def ensure_seed(db: Session) -> None:
    patient = db.get(Patient, "pat_ravi")
    if patient:
        purge_legacy_cohort(db)
        repair_event_order(db)
        return
    reset_demo(db, "rehearsal")
