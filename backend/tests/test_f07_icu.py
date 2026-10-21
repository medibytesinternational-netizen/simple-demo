"""F7 ICU flow sheets: readings with units and timestamps reach the right chart, with a source."""

from __future__ import annotations

from datetime import datetime

import pytest

from .helpers import inject_event

NURSE = {"X-User-Id": "u_anita"}
MGMT = {"X-User-Id": "u_mgmt"}
PHARM = {"X-User-Id": "u_dev"}
HMS = {"X-User-Id": "u_hms"}
WARD = "enc_ipd_1"  # Ward 4B, active
ICU_CATEGORIES = {"ventilator", "infusion", "neuro", "lines"}
WARD_CATEGORIES = {"vitals", "intake_output", "skin", "medication"}


def reading(**over):
    body = {
        "category": "vitals",
        "label": "Heart rate",
        "value": "88",
        "unit": "bpm",
        "device": "Bedside monitor",
        "recorded_at": "2026-10-20T06:00:00",
        "encounter_id": WARD,
    }
    body.update(over)
    return body


def sheet(client, encounter=WARD, **params):
    query = "&".join([f"encounter_id={encounter}"] + [f"{k}={v}" for k, v in params.items()])
    response = client.get(f"/api/icu/flow-sheet?{query}")
    assert response.status_code == 200, response.text
    return response.json()


def make_icu_ward_encounter(ward="ICU Step-down") -> str:
    from app.db import SessionLocal
    from app.models import Encounter

    db = SessionLocal()
    try:
        db.add(Encounter(id="enc_test_icu", patient_id="pat_ravi", kind="ICU", ward=ward, bed="B1",
                         attending="Dr. Meera Shah", admitted_at=datetime(2026, 10, 20, 1, 0), status="active"))
        db.commit()
    finally:
        db.close()
    return "enc_test_icu"


def event_row(event_id: str):
    from app.db import SessionLocal
    from app.models import TimelineEvent

    db = SessionLocal()
    try:
        event = db.get(TimelineEvent, event_id)
        return None if event is None else (event.type, dict(event.payload), event.encounter_id, event.author_name)
    finally:
        db.close()


def device_event_count() -> int:
    from app.db import SessionLocal
    from app.models import TimelineEvent

    db = SessionLocal()
    try:
        return db.query(TimelineEvent).filter(TimelineEvent.type == "device_reading").count()
    finally:
        db.close()


def test_posted_reading_shows_on_sheet_with_unit_time_device_and_real_source(client):
    response = client.post("/api/icu/readings", json=reading(), headers=NURSE)
    assert response.status_code == 200, response.text
    posted = response.json()
    assert posted["duplicate"] is False
    entries = [e for e in sheet(client)["entries"] if e["label"] == "Heart rate"]
    assert len(entries) == 1
    entry = entries[0]
    assert (entry["value"], entry["unit"], entry["device"]) == ("88", "bpm", "Bedside monitor")
    assert entry["recorded_at"] == "2026-10-20T06:00:00"
    assert entry["source_event_id"] == posted["source_event_id"]
    row = event_row(entry["source_event_id"])
    assert row[0] == "device_reading"
    assert row[1]["value"] == "88" and row[1]["chart"] == "ward"
    assert row[3] == "Nurse Anita Rao"  # attributed to the acting user, not to the device field
    assert row[2] == WARD


def test_numeric_value_without_unit_is_refused(client):
    before = device_event_count()
    response = client.post("/api/icu/readings", json=reading(unit=""), headers=NURSE)
    assert response.status_code == 422
    assert "unit" in response.json()["detail"].lower()
    assert device_event_count() == before
    # a value that is not a number needs no unit
    ok = client.post("/api/icu/readings", json=reading(category="lines", label="Peripheral IV", value="Right forearm", unit=""), headers=NURSE)
    assert ok.status_code == 200 and ok.json()["duplicate"] is False


def test_unknown_category_and_bad_time_are_refused(client):
    before = device_event_count()
    assert client.post("/api/icu/readings", json=reading(category="other"), headers=NURSE).status_code == 422
    assert client.post("/api/icu/readings", json=reading(category="nonsense"), headers=NURSE).status_code == 422
    assert client.post("/api/icu/readings", json=reading(recorded_at="yesterday morning"), headers=NURSE).status_code == 422
    assert device_event_count() == before


def test_duplicate_reading_does_not_double(client):
    first = client.post("/api/icu/readings", json=reading(), headers=NURSE).json()
    after_first = device_event_count()
    second = client.post("/api/icu/readings", json=reading(), headers=NURSE)
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["source_event_id"] == first["source_event_id"]
    assert device_event_count() == after_first
    assert len([e for e in sheet(client)["entries"] if e["label"] == "Heart rate"]) == 1
    # a different time is a new reading
    third = client.post("/api/icu/readings", json=reading(recorded_at="2026-10-20T07:00:00"), headers=NURSE).json()
    assert third["duplicate"] is False


@pytest.mark.parametrize("category", sorted(ICU_CATEGORIES | WARD_CATEGORIES))
def test_chart_routing_each_category_on_a_ward(client, category):
    response = client.post(
        "/api/icu/readings",
        json=reading(category=category, label=f"{category} item", value="x", unit=""),
        headers=NURSE,
    )
    assert response.status_code == 200, response.text
    expected = "icu" if category in ICU_CATEGORIES else "ward"
    assert response.json()["chart"] == expected
    entry = next(e for e in sheet(client)["entries"] if e["label"] == f"{category} item")
    assert entry["chart"] == expected


def test_ward_named_icu_routes_everything_to_icu(client):
    encounter = make_icu_ward_encounter()
    for category in sorted(ICU_CATEGORIES | WARD_CATEGORIES):
        response = client.post(
            "/api/icu/readings",
            json=reading(category=category, label=f"{category} item", value="x", unit="", encounter_id=encounter),
            headers=NURSE,
        )
        assert response.status_code == 200, response.text
        assert response.json()["chart"] == "icu"
    entries = sheet(client, encounter)["entries"]
    assert len(entries) == 8
    assert {e["chart"] for e in entries} == {"icu"}


def test_chart_filter_on_sheet_and_generate(client):
    for category in ("ventilator", "vitals"):
        client.post("/api/icu/readings", json=reading(category=category, label=f"{category} item", value="x", unit=""), headers=NURSE)
    both = sheet(client)
    assert {e["chart"] for e in both["entries"] if e["label"].endswith(" item")} == {"icu", "ward"}
    only_icu = sheet(client, chart="icu")
    assert [e["label"] for e in only_icu["entries"]] == ["ventilator item"]
    only_ward = sheet(client, chart="ward")
    assert [e["label"] for e in only_ward["entries"]] == ["vitals item"]
    assert "Ventilator readings" not in only_ward["not_documented"]
    assert "Ventilator readings" not in only_ward["not_documented"]
    assert "Infusions" in only_icu["not_documented"]  # in scope of the icu chart, no data
    assert "Vital signs" not in only_icu["not_documented"]  # belongs to the ward chart
    drafted = client.post(f"/api/icu/flow-sheet/generate?encounter_id={WARD}&chart=icu").json()["draft"]
    assert [e["label"] for e in drafted["content"]["entries"]] == ["ventilator item"]
    drafted_all = client.post(f"/api/icu/flow-sheet/generate?encounter_id={WARD}").json()["draft"]
    assert len(drafted_all["content"]["entries"]) == 2
    assert client.get(f"/api/icu/flow-sheet?encounter_id={WARD}&chart=bogus").status_code == 422


def test_medication_administration_event_appears_as_medication_entry(client):
    event_id = inject_event(
        type="medication_administration",
        title="Flucloxacillin given",
        payload={"drug": "Flucloxacillin", "dose": "1 g", "route": "IV", "status": "given",
                 "given_at": "2026-10-20T08:15:00", "order_event_id": "evt_order_x"},
        source="test_feed",
    )
    entry = next(e for e in sheet(client)["entries"] if e["source_event_id"] == event_id)
    assert entry["category"] == "medication"
    assert entry["label"] == "Flucloxacillin"
    assert entry["value"] == "1 g given"
    assert entry["recorded_at"] == "2026-10-20T08:15:00"
    assert entry["chart"] == "ward"
    assert event_id in {e["source_event_id"] for e in sheet(client, chart="ward")["entries"]}
    assert event_id not in {e["source_event_id"] for e in sheet(client, chart="icu")["entries"]}
    draft = client.post(f"/api/icu/flow-sheet/generate?encounter_id={WARD}").json()["draft"]
    drafted = next(e for e in draft["content"]["entries"] if e["source_event_id"] == event_id)
    assert drafted["value"] == "1 g given"
    assert event_id in draft["evidence_event_ids"]
    assert "Medication administrations" not in draft["content"]["not_documented"]


def test_empty_record_gives_empty_sheet_listing_what_is_missing(fresh):
    data = sheet(fresh)
    assert data["entries"] == []
    assert data["shift_window"] == {"start": "", "end": ""}
    assert set(data["not_documented"]) == {
        "Vital signs", "Ventilator readings", "Infusions", "Intake and output",
        "Neuro observations", "Lines and drains", "Skin and pressure care", "Medication administrations",
    }
    draft = fresh.post(f"/api/icu/flow-sheet/generate?encounter_id={WARD}").json()["draft"]
    assert draft["content"]["entries"] == []
    assert draft["content"]["summary"]["source_event_ids"] == []
    assert "Vital signs" in draft["content"]["not_documented"]
    fresh.post("/api/icu/readings", json=reading(), headers=NURSE)
    after = sheet(fresh)
    assert "Vital signs" not in after["not_documented"]
    assert "Ventilator readings" in after["not_documented"]


def test_nurse_can_record_management_cannot(client):
    assert client.post("/api/icu/readings", json=reading(label="A"), headers=NURSE).status_code == 200
    assert client.post("/api/icu/readings", json=reading(label="B"), headers=HMS).status_code == 200
    assert client.post("/api/icu/readings", json=reading(label="C")).status_code == 200  # doctor, the default user
    before = device_event_count()
    assert client.post("/api/icu/readings", json=reading(label="D"), headers=MGMT).status_code == 403
    assert client.post("/api/icu/readings", json=reading(label="E"), headers=PHARM).status_code == 403
    assert device_event_count() == before


def test_discharged_encounter_refuses_reading(client):
    before = device_event_count()
    response = client.post("/api/icu/readings", json=reading(encounter_id="enc_icu_1"), headers=NURSE)
    assert response.status_code == 409
    assert "locked" in response.json()["detail"]
    assert device_event_count() == before


def test_flow_sheet_draft_is_built_from_events_only(client):
    client.post("/api/icu/readings", json=reading(category="neuro", label="Pupil check", value="equal and reactive", unit=""), headers=NURSE)
    draft = client.post(f"/api/icu/flow-sheet/generate?encounter_id={WARD}").json()["draft"]
    entries = draft["content"]["entries"]
    assert [e["label"] for e in entries] == ["Pupil check"]
    assert entries[0]["value"] == "equal and reactive"
    assert event_row(entries[0]["source_event_id"]) is not None
    assert entries[0]["source_event_id"] in draft["content"]["summary"]["source_event_ids"]


def test_encounter_of_another_patient_is_refused(client):
    assert client.get("/api/icu/flow-sheet?encounter_id=enc_icu_1", headers={"X-Patient-Id": "pat_ravi"}).status_code == 200
    from app.db import SessionLocal
    from app.models import Patient

    db = SessionLocal()
    try:
        other = db.query(Patient).filter(Patient.id != "pat_ravi").first()
        other_id = other.id
    finally:
        db.close()
    assert client.get("/api/icu/flow-sheet?encounter_id=enc_icu_1", headers={"X-Patient-Id": other_id}).status_code == 404
    assert client.post("/api/icu/readings", json=reading(encounter_id="enc_icu_1"), headers={"X-Patient-Id": other_id, **NURSE}).status_code == 404


def test_seeded_icu_stay_still_shows_with_derived_chart(client):
    data = client.get("/api/icu/flow-sheet").json()
    assert data["encounter"]["id"] == "enc_icu_1"
    by_id = {e["source_event_id"]: e for e in data["entries"]}
    assert by_id["evt_icu_infusion_1"]["chart"] == "icu"  # ward is "ICU", so every category is on the icu chart
    assert by_id["evt_icu_bp_1"]["chart"] == "icu"
    assert by_id["evt_icu_bp_1"]["unit"] == "mmHg" and by_id["evt_icu_bp_1"]["device"] == "Bedside monitor"
    assert "Ventilator readings" in data["not_documented"]
    assert "Vital signs" not in data["not_documented"]
    assert client.post("/api/icu/flow-sheet/generate").status_code == 409  # the closed stay is locked
