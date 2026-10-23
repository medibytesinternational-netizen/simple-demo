"""F14 Hospital dashboard: pending tasks, draft discharges, claims and discrepancies for management.

PRD line: "Pending tasks, draft discharges, claims and discrepancies for management." Journey stage 5:
"Dashboard updated." Every cohort row must open onto a real record, and the numbers must be sums of rows.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, SessionLocal
from app.models import Alert, Draft, Task, TimelineEvent
from app.services import medicines
from app.services.rules import evaluate_rules
from app.services.timeline import get_encounter, get_patient, get_state

from .helpers import as_patient

COHORT = ["pat_anita", "pat_joseph", "pat_meera", "pat_arun"]
EXPECTED_RULES = {
    "pat_anita": Counter({"R3": 1}),
    "pat_joseph": Counter({"R3": 2, "R4": 1}),
    "pat_meera": Counter({"R3": 1}),
    "pat_arun": Counter(),
}
EXPECTED_DISCREPANCIES = {"pat_anita": 2, "pat_joseph": 2, "pat_meera": 1, "pat_arun": 0}


def _reconciliation(patient_id: str) -> dict:
    """The reconciliation the medicines route serves, read for a cohort patient through services
    (clinical routes refuse cohort patients: they are dashboard numbers, not open records)."""
    with as_patient(patient_id):
        db = SessionLocal()
        try:
            patient = get_patient(db)
            encounter = get_encounter(db)
            return medicines.reconciliation_with_decisions(db, patient, encounter, get_state(db, patient, encounter))
        finally:
            db.close()


def _dash(client, **headers) -> dict:
    response = client.get("/api/hospital/dashboard", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _row(data: dict, patient_id: str) -> dict:
    return next(row for row in data["patients"] if row["patient_id"] == patient_id)


def _open_alerts(patient_id: str) -> list[Alert]:
    db = SessionLocal()
    try:
        return list(db.scalars(select(Alert).where(Alert.patient_id == patient_id, Alert.status == "open")))
    finally:
        db.close()


def test_each_cohort_patient_has_a_real_record_behind_the_row(client):
    db = SessionLocal()
    try:
        for patient_id in COHORT:
            events = list(db.scalars(select(TimelineEvent).where(TimelineEvent.patient_id == patient_id)))
            types = {event.type for event in events}
            assert len(events) >= 3, patient_id
            assert {"admission_note", "med_order", "vitals", "lab_result"} <= types, patient_id
    finally:
        db.close()
    # Clinical screens stay closed to them.
    for patient_id in COHORT:
        assert client.get(f"/api/patients/{patient_id}/timeline").status_code == 403


def test_cohort_alerts_come_from_the_rules_engine_with_evidence(client):
    db = SessionLocal()
    try:
        for patient_id in COHORT:
            alerts = _open_alerts(patient_id)
            assert Counter(a.rule_id for a in alerts) == EXPECTED_RULES[patient_id], patient_id
            own_events = set(db.scalars(select(TimelineEvent.id).where(TimelineEvent.patient_id == patient_id)))
            for alert in alerts:
                assert alert.evidence_event_ids, alert.title
                assert set(alert.evidence_event_ids) <= own_events
    finally:
        db.close()


def test_no_hand_inserted_cohort_alerts_remain(client):
    db = SessionLocal()
    try:
        rows = list(db.scalars(select(Alert)))
    finally:
        db.close()
    assert rows, "the engine should have made alerts"
    assert [a.id for a in rows if a.id.startswith("alr_cohort_")] == []
    assert [a.id for a in rows if a.rule_id == "COHORT"] == []


def test_evaluating_a_cohort_patient_again_keeps_their_alerts(client):
    before = {pid: sorted((a.id, a.status) for a in _open_alerts(pid)) for pid in COHORT}
    assert before["pat_joseph"], "precondition: Joseph has open alerts"
    for patient_id in COHORT:
        with as_patient(patient_id):
            db = SessionLocal()
            try:
                patient = get_patient(db)
                encounter = get_encounter(db)
                created = evaluate_rules(db, patient, encounter, get_state(db, patient, encounter))
                db.commit()
            finally:
                db.close()
        assert created == [], patient_id
    after = {pid: sorted((a.id, a.status) for a in _open_alerts(pid)) for pid in COHORT}
    assert after == before


def test_ravi_record_is_unchanged_by_the_cohort_seed(client):
    from app.seed import seed_rehearsal

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    scratch = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        seed_rehearsal(scratch)
        base_events = set(scratch.scalars(select(TimelineEvent.id).where(TimelineEvent.patient_id == "pat_ravi")))
        base_alerts = set(scratch.scalars(select(Alert.dedupe_key).where(Alert.patient_id == "pat_ravi")))
    finally:
        scratch.close()
    assert base_events and base_alerts

    db = SessionLocal()
    try:
        events = list(db.scalars(select(TimelineEvent).where(TimelineEvent.patient_id == "pat_ravi")))
        alerts = set(db.scalars(select(Alert.dedupe_key).where(Alert.patient_id == "pat_ravi")))
    finally:
        db.close()
    assert base_events <= {e.id for e in events}
    assert base_alerts <= alerts
    assert [e.id for e in events if e.source == "f14_cohort" or e.id.startswith("evt_f14_")] == []


def test_dashboard_totals_equal_the_sums_of_the_rows(client):
    data = _dash(client)
    rows = data["patients"]
    assert len(rows) == 5
    # Every summary key that has a per-row value is compared with a sum computed here, row by row.
    for key in (
        "draft_discharges", "medicine_discrepancies", "pending_tasks", "pending_drafts",
        "open_alerts", "critical_alerts", "overdue_tasks", "escalated_tasks",
        "pending_documents", "open_referrals", "pending_investigations",
    ):
        expected = 0
        for row in rows:
            expected += row[key]
        assert data["summary"][key] == expected, key
    # The route builds three of these totals by adding up its own rows, so also check each one
    # against a source the route does not use to add them up.
    db = SessionLocal()
    try:
        open_tasks = db.scalars(select(Task).where(Task.status.notin_(["completed", "cancelled"]))).all()
        f9_drafts = db.scalars(
            select(Draft).where(Draft.feature == "F9", Draft.status.in_(["draft_ready", "human_edited"]))
        ).all()
    finally:
        db.close()
    assert data["summary"]["pending_tasks"] == len(open_tasks) > 0
    assert data["summary"]["draft_discharges"] == len(f9_drafts)
    unresolved = 0
    for patient_id in ("pat_ravi", *COHORT):
        unresolved += _reconciliation(patient_id)["unresolved_count"]
    assert data["summary"]["medicine_discrepancies"] == unresolved > 0


def test_rows_count_medicine_discrepancies_from_reconciliation(client):
    data = _dash(client)
    for patient_id, expected in EXPECTED_DISCREPANCIES.items():
        assert _row(data, patient_id)["medicine_discrepancies"] == expected, patient_id
    ravi = client.get("/api/medications/reconciliation").json()
    assert _row(data, "pat_ravi")["medicine_discrepancies"] == len(ravi["discrepancies"]) > 0


def test_generating_a_discharge_draft_raises_draft_discharges_by_one(client):
    before = _dash(client)
    assert _row(before, "pat_ravi")["draft_discharges"] == 0
    assert client.post("/api/discharge/generate").status_code == 200
    after = _dash(client)
    assert _row(after, "pat_ravi")["draft_discharges"] == 1
    assert after["summary"]["draft_discharges"] == before["summary"]["draft_discharges"] + 1
    for patient_id in COHORT:
        assert _row(after, patient_id)["draft_discharges"] == 0
    assert "discharge draft" in _row(after, "pat_ravi")["flags"]


def test_dashboard_is_hospital_wide_whatever_patient_is_open(client):
    reference = _dash(client)
    assert _row(reference, "pat_ravi")["claim_gaps"] == reference["summary"]["claim_gaps"]
    for patient_id in ["pat_ravi", *COHORT]:
        other = _dash(client, **{"X-Patient-Id": patient_id})
        assert other["patients"] == reference["patients"], patient_id
        assert other["summary"] == reference["summary"], patient_id
        assert other["claim"] == reference["claim"], patient_id


def test_the_dashboard_lists_the_whole_cohort(client):
    data = _dash(client)
    assert {row["patient_id"] for row in data["patients"]} == {"pat_ravi", *COHORT}


def test_dashboard_loads_after_the_empty_record_reset(fresh):
    data = _dash(fresh)
    assert [row["patient_id"] for row in data["patients"]] == ["pat_ravi"]
    row = data["patients"][0]
    assert row["draft_discharges"] == 0
    assert row["medicine_discrepancies"] == 0
    assert data["summary"]["draft_discharges"] == 0
    db = SessionLocal()
    try:
        assert list(db.scalars(select(Alert).where(Alert.id.startswith("alr_cohort_", autoescape=True)))) == []
        assert list(db.scalars(select(TimelineEvent).where(TimelineEvent.source == "f14_cohort"))) == []
    finally:
        db.close()
