"""F6: medication reconciliation, medicine orders and administrations.

PRD: "Compares home list against current plan on dose, route, frequency and indication."
Rule 4: a prescription is not an administration. Rule 1: orders pass through a clinician.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from tests.helpers import inject_event, inject_lab

DOCTOR = {"X-User-Id": "u_meera"}
NURSE = {"X-User-Id": "u_anita"}
PHARMACIST = {"X-User-Id": "u_dev"}

ORDER_KEYS = {"drug", "dose", "route", "frequency", "indication", "kind", "status", "reason", "action", "ordered_by"}
ADMIN_KEYS = {"drug", "dose", "route", "status", "given_at", "order_event_id", "note", "recorded_by"}
REASON = "Ordered after ward round review"


def med(kind: str, drug: str, *, dose="500 mg", route="PO", frequency="BD", indication="", minute=0) -> str:
    return inject_event(
        type="med_order",
        title=f"{kind} {drug}",
        payload={
            "drug": drug, "dose": dose, "route": route, "frequency": frequency,
            "indication": indication, "kind": kind, "status": "active",
        },
        source="test_feed",
        author_type="system",
        author_name="Test order feed",
        occurred_at=datetime(2026, 10, 20, 8, minute),
    )


def recon(client) -> dict:
    response = client.get("/api/medications/reconciliation")
    assert response.status_code == 200, response.text
    return response.json()


def by_id(result: dict) -> dict:
    return {item["id"]: item for item in result["discrepancies"]}


def order(client, headers=DOCTOR, **body):
    body.setdefault("reason", REASON)
    return client.post("/api/medications/orders", json=body, headers=headers)


def events_of(client, kind: str) -> list[dict]:
    events = client.get("/api/patients/pat_ravi/timeline").json()["events"]
    return [e for e in events if e["type"] == kind]


def lock_encounter() -> None:
    from app.db import SessionLocal
    from app.models import Encounter

    db = SessionLocal()
    try:
        db.get(Encounter, "enc_ipd_1").status = "discharged"
        db.commit()
    finally:
        db.close()


# ---------- the four comparisons ----------

def test_dose_difference_is_found(fresh):
    home = med("home", "Metformin", dose="500 mg")
    current = med("inpatient", "Metformin", dose="1 g", minute=5)
    item = by_id(recon(fresh))["disc_dose_metformin"]
    assert item["kind"] == "dose_changed"
    assert (item["home_value"], item["current_value"]) == ("500 mg", "1 g")
    assert item["evidence_event_ids"] == [home, current]


def test_route_difference_is_found(fresh):
    med("home", "Amlodipine", route="PO")
    med("inpatient", "Amlodipine", route="IV", minute=5)
    item = by_id(recon(fresh))["disc_route_amlodipine"]
    assert item["kind"] == "route_changed"
    assert (item["home_value"], item["current_value"]) == ("PO", "IV")


def test_frequency_difference_is_found(fresh):
    med("home", "Atorvastatin", frequency="ON")
    med("inpatient", "Atorvastatin", frequency="BD", minute=5)
    item = by_id(recon(fresh))["disc_frequency_atorvastatin"]
    assert item["kind"] == "frequency_changed"
    assert (item["home_value"], item["current_value"]) == ("ON", "BD")


def test_indication_difference_is_found(fresh):
    med("home", "Amlodipine", indication="Hypertension")
    med("inpatient", "Amlodipine", indication="", minute=5)
    item = by_id(recon(fresh))["disc_indication_amlodipine"]
    assert item["kind"] == "indication_missing"
    assert item["home_value"] == "Hypertension"
    assert item["current_value"] == "Not documented"


def test_a_different_indication_is_found_too(fresh):
    med("home", "Amlodipine", indication="Hypertension")
    med("inpatient", "Amlodipine", indication="Angina", minute=5)
    item = by_id(recon(fresh))["disc_indication_amlodipine"]
    assert (item["home_value"], item["current_value"]) == ("Hypertension", "Angina")


def test_no_discrepancy_when_home_and_current_are_equal(fresh):
    med("home", "Amlodipine", dose="10 mg", route="PO", frequency="OD", indication="Hypertension")
    med("inpatient", "Amlodipine", dose="10mg", route="po", frequency="OD", indication="hypertension", minute=5)
    result = recon(fresh)
    assert result["discrepancies"] == []
    assert result["unresolved_count"] == 0


def test_home_medicine_missing_from_orders_is_omitted(fresh):
    home = med("home", "Atorvastatin")
    item = by_id(recon(fresh))["disc_omitted_atorvastatin"]
    assert item["kind"] == "omitted" and item["current_order"] is None
    assert item["evidence_event_ids"] == [home]


# ---------- nothing is invented ----------

def test_metformin_explanation_comes_from_the_record_not_fixed_text(fresh):
    home = med("home", "Metformin", dose="500 mg", frequency="OD")
    current = med("inpatient", "Metformin", dose="500 mg", frequency="OD", minute=5)
    lab = inject_lab("eGFR", "18", "mL/min/1.73m²", "> 90", "low", datetime(2026, 10, 20, 8, 30))
    item = by_id(recon(fresh))["disc_metformin"]
    assert item["kind"] == "contraindicated"
    assert item["home_med"] == "Metformin 500 mg PO OD"
    assert "eGFR 18" in item["explanation"] and "22" not in item["explanation"]
    assert item["home_value"] == "eGFR 18 mL/min/1.73m²"
    assert item["evidence_event_ids"] == [current, lab]
    assert home not in item["evidence_event_ids"]


def test_interaction_names_come_from_the_record(fresh):
    med("inpatient", "Warfarin", dose="5 mg", frequency="OD")
    med("inpatient", "Naproxen", dose="250 mg", frequency="BD", minute=5)
    item = by_id(recon(fresh))["disc_warfarin_naproxen"]
    assert item["kind"] == "interaction"
    assert item["home_med"] == "Warfarin + Naproxen"
    assert "Naproxen" in item["explanation"] and "ibuprofen" not in item["explanation"].lower()


def test_reconciliation_module_holds_no_fixed_patient_text():
    source = (Path(__file__).resolve().parent.parent / "app" / "services" / "reconciliation.py").read_text()
    for literal in ("Metformin 1 g BD", "eGFR 22", "Both active", "Warfarin + Ibuprofen", "CKD"):
        assert literal not in source, literal


def test_interaction_pairs_match_the_safety_rules():
    from app.services.reconciliation import INTERACTION_PAIRS, LOCAL_INTERACTION_PAIRS
    from app.services import rules

    assert INTERACTION_PAIRS == rules.INTERACTION_PAIRS
    assert LOCAL_INTERACTION_PAIRS == rules.INTERACTION_PAIRS


def test_discrepancy_ids_are_stable_and_start_open(client):
    first = recon(client)
    second = recon(client)
    assert [i["id"] for i in first["discrepancies"]] == [i["id"] for i in second["discrepancies"]]
    assert first["discrepancies"]
    assert {i["status"] for i in first["discrepancies"]} == {"open"}
    assert first["unresolved_count"] == len(first["discrepancies"])


# ---------- resolving ----------

def test_resolve_stores_the_decision_and_changes_no_order(client):
    before = recon(client)
    target = next(i for i in before["discrepancies"] if i["kind"] == "contraindicated")
    meds_before = client.get("/api/medications").json()
    orders_before = len(events_of(client, "med_order"))

    response = client.post(
        f"/api/medications/reconciliation/{target['id']}/resolve",
        json={"decision": "stop", "note": "eGFR too low, stop metformin"},
        headers=DOCTOR,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    proposed = body["proposed_order_change"]
    assert proposed["action"] == "stop" and proposed["drug"] == target["drug"] and proposed["ordered"] is False
    assert proposed["evidence_event_ids"] == target["evidence_event_ids"]
    assert body["decided_by"] == "Dr. Meera Shah"

    assert client.get("/api/medications").json() == meds_before
    assert len(events_of(client, "med_order")) == orders_before
    assert client.get("/api/medications/administrations").json()["administrations"] == []

    after = recon(client)
    resolved = by_id(after)[target["id"]]
    assert resolved["status"] == "resolved" and resolved["decision"] == "stop"
    assert resolved["decided_by"] == "Dr. Meera Shah" and resolved["note"] == "eGFR too low, stop metformin"
    assert after["unresolved_count"] == before["unresolved_count"] - 1

    events = events_of(client, "reconciliation_decision")
    assert len(events) == 1
    assert events[0]["author_type"] == "human" and events[0]["payload"]["discrepancy_id"] == target["id"]


def test_continue_decision_proposes_no_change(client):
    target = recon(client)["discrepancies"][0]
    response = client.post(
        f"/api/medications/reconciliation/{target['id']}/resolve",
        json={"decision": "continue", "note": "Reviewed, continue as ordered"},
        headers=DOCTOR,
    )
    assert response.status_code == 200
    assert response.json()["proposed_order_change"] is None


def test_hold_and_change_decisions_propose_but_create_no_order(client):
    ids = [i["id"] for i in recon(client)["discrepancies"]][:2]
    orders_before = len(events_of(client, "med_order"))
    for ident, decision in zip(ids, ("hold", "change")):
        response = client.post(
            f"/api/medications/reconciliation/{ident}/resolve",
            json={"decision": decision, "note": "Needs a prescriber order"},
            headers=DOCTOR,
        )
        assert response.json()["proposed_order_change"]["decision"] == decision
    assert len(events_of(client, "med_order")) == orders_before


def test_resolve_note_needs_ten_characters(client):
    ident = recon(client)["discrepancies"][0]["id"]
    response = client.post(
        f"/api/medications/reconciliation/{ident}/resolve", json={"decision": "continue", "note": "too short"}, headers=DOCTOR
    )
    assert response.status_code == 422
    assert recon(client)["discrepancies"][0]["status"] == "open"


def test_resolve_unknown_discrepancy_is_404(client):
    response = client.post(
        "/api/medications/reconciliation/disc_nothing/resolve",
        json={"decision": "continue", "note": "A long enough note"},
        headers=DOCTOR,
    )
    assert response.status_code == 404


def test_pharmacist_can_resolve_but_nurse_cannot(client):
    ident = recon(client)["discrepancies"][0]["id"]
    body = {"decision": "continue", "note": "Checked with the prescriber"}
    assert client.post(f"/api/medications/reconciliation/{ident}/resolve", json=body, headers=NURSE).status_code == 403
    assert recon(client)["discrepancies"][0]["status"] == "open"
    response = client.post(f"/api/medications/reconciliation/{ident}/resolve", json=body, headers=PHARMACIST)
    assert response.status_code == 200
    assert by_id(recon(client))[ident]["decided_by"] == "Pharmacist Dev Patel"


def test_a_decision_reopens_when_the_order_it_was_made_on_changes(client):
    target = next(i for i in recon(client)["discrepancies"] if i["id"] == "disc_metformin")
    client.post(
        f"/api/medications/reconciliation/{target['id']}/resolve",
        json={"decision": "continue", "note": "Continue for now, recheck"},
        headers=DOCTOR,
    )
    assert by_id(recon(client))["disc_metformin"]["status"] == "resolved"
    assert order(client, action="change", drug="Metformin", dose="500 mg").status_code == 200
    reopened = by_id(recon(client))["disc_metformin"]
    assert reopened["status"] == "open"
    assert reopened["earlier_decision"]["decision"] == "continue"


def test_unresolved_discrepancies_lists_only_open_items(client):
    from app.db import SessionLocal
    from app.services.medicines import unresolved_discrepancies
    from app.services.timeline import get_encounter, get_patient, get_state

    def open_ids() -> list[str]:
        db = SessionLocal()
        try:
            patient, encounter = get_patient(db), get_encounter(db)
            return [i["id"] for i in unresolved_discrepancies(db, patient, encounter, get_state(db, patient, encounter))]
        finally:
            db.close()

    before = open_ids()
    assert before == [i["id"] for i in recon(client)["discrepancies"]]
    client.post(
        f"/api/medications/reconciliation/{before[0]}/resolve",
        json={"decision": "continue", "note": "Reviewed and accepted"},
        headers=DOCTOR,
    )
    assert open_ids() == before[1:]


def test_resolve_is_refused_on_a_discharged_encounter(client):
    ident = recon(client)["discrepancies"][0]["id"]
    lock_encounter()
    response = client.post(
        f"/api/medications/reconciliation/{ident}/resolve",
        json={"decision": "continue", "note": "Late decision attempt"},
        headers=DOCTOR,
    )
    assert response.status_code == 409


# ---------- orders ----------

def test_start_writes_a_human_order_with_the_exact_payload(fresh):
    response = order(fresh, action="start", drug="Paracetamol", dose="500 mg", route="PO", frequency="QDS", indication="Pain")
    assert response.status_code == 200, response.text
    event = response.json()["event"]
    assert event["type"] == "med_order" and event["author_type"] == "human"
    assert event["author_name"] == "Dr. Meera Shah"
    assert event["payload"] == {
        "drug": "Paracetamol", "dose": "500 mg", "route": "PO", "frequency": "QDS", "indication": "Pain",
        "kind": "inpatient", "status": "active", "reason": REASON, "action": "start", "ordered_by": "Dr. Meera Shah",
    }
    assert set(event["payload"]) == ORDER_KEYS
    current = fresh.get("/api/medications").json()["current_medications"]
    assert [m["drug"] for m in current] == ["Paracetamol"] and current[0]["event_id"] == event["id"]


def test_start_twice_is_400_and_says_to_use_change(fresh):
    assert order(fresh, action="start", drug="Paracetamol", dose="500 mg").status_code == 200
    again = order(fresh, action="start", drug="paracetamol", dose="1 g")
    assert again.status_code == 400 and "change" in again.json()["detail"].lower()
    assert len(fresh.get("/api/medications").json()["current_medications"]) == 1


def test_stop_needs_an_active_order(fresh):
    assert order(fresh, action="stop", drug="Paracetamol").status_code == 400
    assert events_of(fresh, "med_order") == []


def test_stop_removes_the_drug_everywhere_it_is_read(fresh):
    from app.db import SessionLocal
    from app.services.context import build_context
    from app.services.timeline import get_encounter, get_patient, get_state

    def discharge_context_drugs() -> list[str]:
        db = SessionLocal()
        try:
            patient, encounter = get_patient(db), get_encounter(db)
            context = build_context(db, patient, encounter, get_state(db, patient, encounter), "F9")
            return [m["drug"] for m in context["active_medications"]]
        finally:
            db.close()

    order(fresh, action="start", drug="Paracetamol", dose="500 mg")
    assert discharge_context_drugs() == ["Paracetamol"]
    stopped = order(fresh, action="stop", drug="Paracetamol", reason="Pain resolved on review")
    assert stopped.status_code == 200
    payload = stopped.json()["event"]["payload"]
    assert payload["status"] == "stopped" and payload["action"] == "stop" and payload["dose"] == "500 mg"
    assert fresh.get("/api/medications").json()["current_medications"] == []
    assert discharge_context_drugs() == []


def test_change_keeps_the_fields_it_was_not_given(fresh):
    order(fresh, action="start", drug="Paracetamol", dose="500 mg", route="PO", frequency="QDS", indication="Pain")
    response = order(fresh, action="change", drug="paracetamol", dose="1 g")
    assert response.status_code == 200, response.text
    payload = response.json()["event"]["payload"]
    assert (payload["dose"], payload["route"], payload["frequency"], payload["indication"]) == ("1 g", "PO", "QDS", "Pain")
    assert payload["drug"] == "Paracetamol" and payload["action"] == "change" and payload["status"] == "active"
    current = fresh.get("/api/medications").json()["current_medications"]
    assert [(m["drug"], m["dose"]) for m in current] == [("Paracetamol", "1 g")]


def test_change_needs_an_active_order_and_a_new_value(fresh):
    assert order(fresh, action="change", drug="Paracetamol", dose="1 g").status_code == 400
    order(fresh, action="start", drug="Paracetamol", dose="500 mg")
    assert order(fresh, action="change", drug="Paracetamol").status_code == 400
    assert order(fresh, action="change", drug="Paracetamol", dose="500mg").status_code == 400


def test_order_reason_needs_ten_characters(fresh):
    response = order(fresh, action="start", drug="Paracetamol", reason="short")
    assert response.status_code == 422
    assert events_of(fresh, "med_order") == []


def test_only_a_doctor_can_order(fresh):
    for headers in (NURSE, PHARMACIST):
        assert order(fresh, headers=headers, action="start", drug="Paracetamol").status_code == 403
    assert events_of(fresh, "med_order") == []


def test_ordering_is_refused_on_a_discharged_encounter(fresh):
    lock_encounter()
    response = order(fresh, action="start", drug="Paracetamol")
    assert response.status_code == 409
    assert events_of(fresh, "med_order") == []


def test_a_prescription_is_not_an_administration(fresh):
    order(fresh, action="start", drug="Paracetamol", dose="500 mg")
    order(fresh, action="change", drug="Paracetamol", dose="1 g")
    assert fresh.get("/api/medications/administrations").json()["administrations"] == []
    assert events_of(fresh, "medication_administration") == []


def test_ordering_metformin_at_low_egfr_returns_the_new_alert(fresh):
    inject_lab("eGFR", "18", "mL/min/1.73m²", "> 90", "low", datetime(2026, 10, 20, 8, 30))
    response = order(fresh, action="start", drug="Metformin", dose="500 mg", frequency="BD")
    assert response.status_code == 200, response.text
    body = response.json()
    alerts = [a for a in body["new_alerts"] if a["rule_id"] == "R1"]
    assert len(alerts) == 1
    assert body["event"]["id"] in alerts[0]["evidence_event_ids"]


# ---------- administrations ----------

def start_paracetamol(client) -> str:
    return order(client, action="start", drug="Paracetamol", dose="500 mg", route="PO").json()["event"]["id"]


def give(client, event_id, headers=NURSE, **body):
    body.setdefault("status", "given")
    return client.post(f"/api/medications/orders/{event_id}/administrations", json=body, headers=headers)


def test_nurse_records_a_given_dose_with_the_exact_payload(fresh):
    order_id = start_paracetamol(fresh)
    response = give(fresh, order_id, given_at="2026-10-20T09:30:00", note="Taken with water")
    assert response.status_code == 200, response.text
    event = response.json()["event"]
    assert event["type"] == "medication_administration" and event["author_type"] == "human"
    assert event["payload"] == {
        "drug": "Paracetamol", "dose": "500 mg", "route": "PO", "status": "given",
        "given_at": "2026-10-20T09:30:00", "order_event_id": order_id, "note": "Taken with water",
        "recorded_by": "Nurse Anita Rao",
    }
    assert set(event["payload"]) == ADMIN_KEYS
    listed = fresh.get("/api/medications/administrations").json()["administrations"]
    assert [(a["order_event_id"], a["status"], a["event_id"]) for a in listed] == [(order_id, "given", event["id"])]


def test_given_at_defaults_to_the_demo_clock(fresh):
    order_id = start_paracetamol(fresh)
    before = datetime.fromisoformat(fresh.get("/api/meta").json()["demo_now"])
    given_at = datetime.fromisoformat(give(fresh, order_id).json()["event"]["payload"]["given_at"])
    assert 0 <= (given_at - before).total_seconds() < 3600


def test_held_and_refused_doses_are_recorded_as_such(fresh):
    order_id = start_paracetamol(fresh)
    assert give(fresh, order_id, status="held", note="Nil by mouth").json()["event"]["payload"]["status"] == "held"
    assert give(fresh, order_id, status="refused").json()["event"]["payload"]["status"] == "refused"
    statuses = {a["status"] for a in fresh.get("/api/medications/administrations").json()["administrations"]}
    assert statuses == {"held", "refused"}


def test_administration_status_and_time_are_validated(fresh):
    order_id = start_paracetamol(fresh)
    assert give(fresh, order_id, status="bogus").status_code == 422
    assert give(fresh, order_id, given_at="yesterday morning").status_code == 400
    assert fresh.get("/api/medications/administrations").json()["administrations"] == []


def test_a_doctor_cannot_record_a_given_dose(fresh):
    order_id = start_paracetamol(fresh)
    assert give(fresh, order_id, headers=DOCTOR).status_code == 403
    assert give(fresh, order_id, headers=PHARMACIST).status_code == 403
    assert fresh.get("/api/medications/administrations").json()["administrations"] == []


def test_giving_needs_the_current_active_order(fresh):
    first = start_paracetamol(fresh)
    second = order(fresh, action="change", drug="Paracetamol", dose="1 g").json()["event"]["id"]
    assert give(fresh, first).status_code == 400  # superseded
    assert give(fresh, second).status_code == 200
    order(fresh, action="stop", drug="Paracetamol", reason="Course complete, stop")
    assert give(fresh, second).status_code == 400  # stopped
    assert len(fresh.get("/api/medications/administrations").json()["administrations"]) == 1


def test_giving_against_a_home_medicine_or_a_non_order_is_refused(fresh):
    home = med("home", "Amlodipine", dose="10 mg")
    lab = inject_lab("eGFR", "60", "mL/min/1.73m²", "> 90", "low", datetime(2026, 10, 20, 8, 30))
    assert give(fresh, home).status_code == 400
    assert give(fresh, lab).status_code == 400
    assert give(fresh, "evt_does_not_exist").status_code == 404


def test_giving_is_refused_on_a_discharged_encounter(fresh):
    order_id = start_paracetamol(fresh)
    lock_encounter()
    assert give(fresh, order_id).status_code == 409
    assert fresh.get("/api/medications/administrations").json()["administrations"] == []


# ---------- credits ----------

def test_generating_the_reconciliation_charges_two_credits(client):
    before = client.get("/api/credits").json()["balance"]
    response = client.post("/api/medications/reconciliation/generate", headers=PHARMACIST)
    assert response.status_code == 200, response.text
    assert client.get("/api/credits").json()["balance"] == before - 2
    assert client.get("/api/credits").json()["ledger"][0]["operation"] == "medicine_reconciliation"


def test_generated_draft_follows_the_record_and_keeps_its_evidence(fresh):
    home = med("home", "Metformin", dose="500 mg")
    current = med("inpatient", "Metformin", dose="850 mg", minute=5)
    draft = fresh.post("/api/medications/reconciliation/generate").json()["draft"]["content"]
    line = next(d for d in draft["discrepancies"] if d["kind"] == "dose_changed")
    assert (line["home_value"], line["current_value"]) == ("500 mg", "850 mg")
    assert line["evidence_event_ids"] == [home, current]
    assert draft["summary"].startswith("1 medication difference found")
    assert "1 still need" in draft["summary"]
