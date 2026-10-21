"""F14: give each hospital-cohort patient a real record, then let the rules engine raise their alerts.

The base seed creates four other patients (patient, encounter, one task) and a hand-typed alert for
two of them. Here each gets an approved admission note, vitals, results and medicine orders, and the
hand-typed ``alr_cohort_*`` alerts are replaced by alerts made by ``evaluate_rules`` from that record.
Ravi's data is not touched.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Alert, Encounter, Patient, Task, TimelineEvent
from ..services import identity
from ..services.rules import evaluate_rules
from ..services.timeline import add_audit, get_state
from . import seed_hook

SOURCE = "f14_cohort"


def _lab(name, value, unit, ref, flag, review, at):
    return ("lab_result", name, value, unit, ref, flag, review, at)


def _med(drug, dose, route, freq, kind, indication, at):
    return ("med_order", drug, dose, route, freq, kind, indication, at)


# patient id -> (encounter id, doctor, admission note, vitals, labs, medicines, task evidence key)
COHORT: dict[str, dict] = {
    "pat_anita": {
        "short": "anita",
        "doctor": "Dr. Meera Shah",
        "admission": (
            datetime(2026, 10, 19, 10, 45),
            "Admitted with decompensated heart failure on a background of atrial fibrillation. "
            "Sulfonamide allergy documented. Plan: fluid balance and daily weights, renal function and "
            "potassium monitoring, review the ACE inhibitor dose.",
            {
                "chief_complaint": "Breathlessness and ankle swelling",
                "assessment": ["Decompensated heart failure", "Atrial fibrillation"],
                "plan": ["Daily weights", "Renal function and potassium monitoring", "Review ACE inhibitor dose"],
            },
        ),
        "vitals": (
            datetime(2026, 10, 20, 6, 0),
            "Temp 36.8°C, HR 96, BP 118/72, RR 20, SpO2 94% on room air.",
            {"temperature_c": 36.8, "heart_rate": 96, "systolic": 118, "diastolic": 72,
             "respiratory_rate": 20, "spo2": 94, "recorded_at": "2026-10-20T06:00:00"},
        ),
        "labs": [
            _lab("Potassium", 5.6, "mmol/L", "3.5 - 5.1", "high", "unreviewed", "2026-10-20T06:30:00"),
            _lab("Creatinine", 1.6, "mg/dL", "0.6 - 1.1", "high", "reviewed", "2026-10-20T06:30:00"),
            _lab("eGFR", 41, "mL/min/1.73m²", "> 90", "low", "reviewed", "2026-10-20T06:30:00"),
        ],
        "meds": [
            _med("Ramipril", "2.5 mg", "PO", "OD", "home", "Heart failure", "2026-09-01T08:00:00"),
            _med("Bisoprolol", "2.5 mg", "PO", "OD", "home", "Heart failure", "2026-09-01T08:00:00"),
            _med("Apixaban", "5 mg", "PO", "BD", "home", "Atrial fibrillation", "2026-09-01T08:00:00"),
            _med("Ramipril", "5 mg", "PO", "OD", "inpatient", "Heart failure", "2026-10-19T12:00:00"),
            _med("Apixaban", "5 mg", "PO", "BD", "inpatient", "Atrial fibrillation", "2026-10-19T12:00:00"),
        ],
        "task_evidence": ("lab_result", "Potassium"),
    },
    "pat_joseph": {
        "short": "joseph",
        "doctor": "Dr. Arjun Rao",
        "admission": (
            datetime(2026, 10, 19, 14, 15),
            "Admitted with an exacerbation of COPD. Oxygen requirement rose from 2 L to 6 L/min. "
            "Plan: nebulised bronchodilators, oral steroid, repeat blood gas after the oxygen change.",
            {
                "chief_complaint": "Worsening breathlessness",
                "assessment": ["COPD exacerbation", "CKD stage 2"],
                "plan": ["Bronchodilators", "Oral steroid", "Repeat ABG after oxygen change"],
            },
        ),
        "vitals": (
            datetime(2026, 10, 20, 7, 0),
            "Temp 37.9°C, HR 104, BP 138/86, RR 26, SpO2 91% on 6 L/min oxygen.",
            {"temperature_c": 37.9, "heart_rate": 104, "systolic": 138, "diastolic": 86,
             "respiratory_rate": 26, "spo2": 91, "oxygen_l_min": 6, "recorded_at": "2026-10-20T07:00:00"},
        ),
        "labs": [
            _lab("PaO2", 58, "mmHg", "80 - 100", "low", "unreviewed", "2026-10-20T07:15:00"),
            _lab("INR", 3.4, "", "2.0 - 3.0", "high", "unreviewed", "2026-10-20T07:15:00"),
            _lab("CRP", 64, "mg/L", "0 - 5", "high", "reviewed", "2026-10-19T16:00:00"),
            _lab("Creatinine", 1.3, "mg/dL", "0.7 - 1.3", "normal", "reviewed", "2026-10-19T16:00:00"),
        ],
        "meds": [
            _med("Salbutamol inhaler", "100 mcg", "INH", "PRN", "home", "COPD", "2026-09-01T08:00:00"),
            _med("Tiotropium", "18 mcg", "INH", "OD", "home", "COPD", "2026-09-01T08:00:00"),
            _med("Warfarin", "3 mg", "PO", "OD", "home", "Anticoagulation", "2026-09-01T18:00:00"),
            _med("Ibuprofen", "400 mg", "PO", "PRN", "home", "Pain", "2026-09-01T08:00:00"),
            _med("Salbutamol inhaler", "100 mcg", "INH", "QDS", "inpatient", "COPD", "2026-10-19T15:00:00"),
            _med("Tiotropium", "18 mcg", "INH", "OD", "inpatient", "COPD", "2026-10-19T15:00:00"),
            _med("Warfarin", "3 mg", "PO", "OD", "inpatient", "Anticoagulation", "2026-10-19T15:00:00"),
            _med("Ibuprofen", "400 mg", "PO", "PRN", "inpatient", "Pain", "2026-10-19T15:00:00"),
            _med("Prednisolone", "30 mg", "PO", "OD", "inpatient", "COPD exacerbation", "2026-10-19T15:00:00"),
        ],
        "task_evidence": ("vitals", None),
    },
    "pat_meera": {
        "short": "meera",
        "doctor": "Dr. Kavita Menon",
        "admission": (
            datetime(2026, 10, 20, 7, 45),
            "Day-care surgical admission, post-operative day 1. Latex allergy documented. "
            "Plan: analgesia, haemoglobin check, mobilise, confirm the discharge medication list.",
            {
                "chief_complaint": "Post-operative review",
                "assessment": ["Post-operative day 1"],
                "plan": ["Analgesia", "Haemoglobin check", "Confirm discharge medication list"],
            },
        ),
        "vitals": (
            datetime(2026, 10, 20, 8, 30),
            "Temp 36.9°C, HR 82, BP 122/78, RR 16, SpO2 99% on room air.",
            {"temperature_c": 36.9, "heart_rate": 82, "systolic": 122, "diastolic": 78,
             "respiratory_rate": 16, "spo2": 99, "recorded_at": "2026-10-20T08:30:00"},
        ),
        "labs": [
            _lab("Haemoglobin", 9.4, "g/dL", "12.0 - 15.5", "low", "unreviewed", "2026-10-20T08:00:00"),
            _lab("Creatinine", 0.8, "mg/dL", "0.6 - 1.1", "normal", "reviewed", "2026-10-20T08:00:00"),
        ],
        "meds": [
            _med("Levothyroxine", "50 mcg", "PO", "OD", "home", "Thyroid replacement", "2026-09-01T07:00:00"),
            _med("Paracetamol", "1 g", "PO", "QDS", "home", "Pain", "2026-09-01T08:00:00"),
            _med("Paracetamol", "1 g", "PO", "QDS", "inpatient", "Pain", "2026-10-20T08:00:00"),
        ],
        "task_evidence": ("med_order", "Levothyroxine"),
    },
    "pat_arun": {
        "short": "arun",
        "doctor": "Dr. Arjun Rao",
        "admission": (
            datetime(2026, 10, 16, 9, 20),
            "Admitted with community-acquired pneumonia. No known drug allergies. "
            "Plan: oral antibiotics, inflammatory markers, discharge when afebrile.",
            {
                "chief_complaint": "Fever and productive cough",
                "assessment": ["Community-acquired pneumonia"],
                "plan": ["Oral antibiotics", "Monitor CRP", "Discharge when afebrile"],
            },
        ),
        "vitals": (
            datetime(2026, 10, 20, 7, 0),
            "Temp 36.7°C, HR 76, BP 126/80, RR 16, SpO2 98% on room air.",
            {"temperature_c": 36.7, "heart_rate": 76, "systolic": 126, "diastolic": 80,
             "respiratory_rate": 16, "spo2": 98, "recorded_at": "2026-10-20T07:00:00"},
        ),
        "labs": [
            _lab("CRP", 98, "mg/L", "0 - 5", "high", "reviewed", "2026-10-17T07:00:00"),
            _lab("CRP", 14, "mg/L", "0 - 5", "high", "reviewed", "2026-10-20T06:00:00"),
            _lab("White cell count", 8.9, "10^3/µL", "4.0 - 11.0", "normal", "reviewed", "2026-10-20T06:00:00"),
        ],
        "meds": [
            _med("Co-amoxiclav", "625 mg", "PO", "TDS", "inpatient", "Pneumonia", "2026-10-16T10:00:00"),
            _med("Clarithromycin", "500 mg", "PO", "BD", "inpatient", "Pneumonia", "2026-10-16T10:00:00"),
        ],
        "task_evidence": ("vitals", None),
    },
}


def _event(db: Session, event_id: str, patient_id: str, encounter_id: str, **fields) -> TimelineEvent:
    occurred_at = fields.pop("occurred_at")
    author_name = fields.pop("author_name")
    author_type = fields.pop("author_type", "human")
    event = TimelineEvent(
        id=event_id,
        patient_id=patient_id,
        encounter_id=encounter_id,
        source=SOURCE,
        author_type=author_type,
        author_name=author_name,
        status="approved",
        occurred_at=occurred_at,
        created_at=occurred_at,
        approved_by=author_name,
        approved_at=occurred_at,
        **fields,
    )
    db.add(event)
    audit = add_audit(
        db,
        "timeline_committed",
        "timeline_event",
        event_id,
        patient_id,
        actor_type="system",
        actor_name="Demo seed",
        after={"type": event.type, "title": event.title, "source": SOURCE},
        meta={"seeded": True},
    )
    # Backdated so the hospital "recent audit" list keeps showing live activity first.
    audit.created_at = occurred_at
    return event


def _seed_record(db: Session, patient_id: str, spec: dict) -> dict[str, str]:
    """Write one patient's events. Returns {"vitals": id, "lab:<name>": id, "med:<drug>": id}."""
    encounter = db.scalar(
        select(Encounter).where(Encounter.patient_id == patient_id).order_by(Encounter.admitted_at.desc())
    )
    short = spec["short"]
    doctor = spec["doctor"]
    ids: dict[str, str] = {}
    n = 0

    def next_id() -> str:
        nonlocal n
        n += 1
        return f"evt_f14_{short}_{n:02d}"

    when, body, payload = spec["admission"]
    ids["admission"] = next_id()
    _event(
        db, ids["admission"], patient_id, encounter.id,
        type="admission_note", subtype="f2", title="Admission assessment",
        body_text=body, payload=payload, occurred_at=when, author_name=doctor,
    )
    when, body, payload = spec["vitals"]
    ids["vitals"] = next_id()
    _event(
        db, ids["vitals"], patient_id, encounter.id,
        type="vitals", title="Observations", body_text=body, payload=payload,
        occurred_at=when, author_name="Nursing chart",
    )
    for _, name, value, unit, ref, flag, review, collected in spec["labs"]:
        event_id = next_id()
        ids[f"lab:{name}"] = event_id
        _event(
            db, event_id, patient_id, encounter.id,
            type="lab_result", title=f"{name} — {value} {unit}".strip(),
            body_text=f"{name}: {value} {unit} (reference {ref}); flag {flag}; {review}.",
            payload={
                "name": name, "value": value, "unit": unit, "reference_range": ref,
                "flag": flag, "review_status": review, "collected_at": collected,
            },
            occurred_at=datetime.fromisoformat(collected), author_name="Laboratory",
        )
    for _, drug, dose, route, freq, kind, indication, started in spec["meds"]:
        event_id = next_id()
        ids[f"med:{drug}:{kind}"] = event_id
        _event(
            db, event_id, patient_id, encounter.id,
            type="med_order",
            subtype="home" if kind == "home" else "inpatient",
            title=f"{'Home' if kind == 'home' else 'Inpatient'} medication — {drug} {dose} {freq}",
            body_text=f"{drug} {dose} {freq} {route} ({kind}, active)",
            payload={
                "drug": drug, "dose": dose, "route": route, "frequency": freq,
                "kind": kind, "status": "active", "indication": indication,
            },
            occurred_at=datetime.fromisoformat(started), author_name=doctor,
        )
    return ids


def _link_task(db: Session, patient_id: str, spec: dict, ids: dict[str, str]) -> None:
    """Point the existing cohort task at the record entry that explains it."""
    kind, name = spec["task_evidence"]
    if kind == "lab_result":
        evidence = ids.get(f"lab:{name}")
    elif kind == "med_order":
        evidence = ids.get(f"med:{name}:home")
    else:
        evidence = ids.get("vitals")
    for task in db.scalars(select(Task).where(Task.patient_id == patient_id)):
        if not task.source_event_id:
            task.source_event_id = evidence


@seed_hook
def seed_cohort_records(db: Session, mode: str) -> None:
    if mode != "rehearsal":
        return
    present = {p for p in db.scalars(select(Patient.id)) if p in COHORT}
    if not present:
        return
    db.execute(delete(Alert).where(Alert.id.startswith("alr_cohort_", autoescape=True)))
    all_ids: dict[str, dict[str, str]] = {}
    for patient_id, spec in COHORT.items():
        if patient_id in present:
            all_ids[patient_id] = _seed_record(db, patient_id, spec)
            _link_task(db, patient_id, spec, all_ids[patient_id])
    db.flush()
    db.commit()

    for patient_id in all_ids:
        patient = db.get(Patient, patient_id)
        encounter = db.scalar(
            select(Encounter).where(Encounter.patient_id == patient_id).order_by(Encounter.admitted_at.desc())
        )
        tokens = identity.set_context(None, patient_id)
        try:
            state = get_state(db, patient, encounter)
            evaluate_rules(db, patient, encounter, state)
        finally:
            identity.reset_context(tokens)
    db.commit()
