"""F13: documented services are compared with charges by tariff code, with amounts from the tariff.

Bed-days depend on the clock, so every test that reads the seeded encounter pins its dates first.
"""

from __future__ import annotations

from datetime import datetime

from app.db import SessionLocal
from app.models import BillLineItem, Encounter, Patient
from app.models_ext.f13_tariff import TariffItem
from app.seeds.f13_tariff import DEFAULT_TARIFF, upsert_tariff
from app.services.leakage import leakage
from tests.helpers import inject_event

BILLING = {"X-User-Id": "u_billing"}
PINNED_START = datetime(2026, 10, 18, 14, 10)
PINNED_END = datetime(2026, 10, 20, 9, 0)  # 1 whole day for the seeded encounter, whatever the clock says


def _pin(admitted=PINNED_START, discharged=PINNED_END, encounter_id="enc_ipd_1"):
    db = SessionLocal()
    try:
        enc = db.get(Encounter, encounter_id)
        enc.admitted_at, enc.discharged_at = admitted, discharged
        db.commit()
    finally:
        db.close()


def _leak(encounter_id="enc_ipd_1") -> dict:
    db = SessionLocal()
    try:
        return leakage(db, db.get(Patient, "pat_ravi"), db.get(Encounter, encounter_id), {})
    finally:
        db.close()


def _by_code(result: dict, code: str, status: str | None = None) -> list[dict]:
    return [f for f in result["findings"] if f["code"] == code and (status is None or f["billing_status"] == status)]


def _add_line(code: str, amount: float, *, docs=("evt_x",), line_id="bill_f13", encounter_id="enc_ipd_1", description="Test line"):
    db = SessionLocal()
    try:
        db.add(BillLineItem(
            id=line_id, patient_id="pat_ravi", encounter_id=encounter_id, code=code,
            description=description, amount=amount, documentation_event_ids=list(docs),
        ))
        db.commit()
    finally:
        db.close()


def _given(drug="Sodium chloride 0.9%", route="IV", status="given", **extra) -> str:
    return inject_event(
        type="medication_administration",
        title=f"{drug} {status}",
        payload={"drug": drug, "dose": "500 mL", "route": route, "status": status,
                 "given_at": "2026-10-20T08:00:00", **extra},
        source="test_feed",
        author_type="human",
    )


# ---------- Seeded gaps are still found ----------

def test_rehearsal_finds_exactly_the_seeded_gaps(client):
    _pin()
    result = _leak()
    pairs = {(f["code"], f["billing_status"]) for f in result["findings"]}
    assert pairs == {("97597", "unbilled"), ("J01", "underbilled"), ("PT01", "underbilled"), ("PT01", "unsupported")}
    assert result["count"] == 4
    debridement = _by_code(result, "97597")[0]
    assert debridement["procedure"] == "Wound debridement"
    assert debridement["evidence_event_ids"] == ["evt_seed_procedure"]
    assert debridement["expected_amount"] == 3500  # from the tariff, not typed on a bill row
    assert _by_code(result, "J01")[0]["variance"] == 1000
    assert _by_code(result, "PT01", "underbilled")[0]["variance"] == 1200
    assert "evt_seed_billing" in _by_code(result, "PT01", "unsupported")[0]["evidence_event_ids"]
    assert all(f["evidence_event_ids"] for f in result["findings"])
    assert result["leakage_amount"] == 3500 + 1000 + 1200


def test_leakage_ignores_the_typed_expected_amount_on_bill_rows(client):
    _pin()
    db = SessionLocal()
    try:
        db.get(BillLineItem, "bill_antibiotics").expected_amount = 99999
        db.get(BillLineItem, "bill_nursing").expected_amount = 99999
        db.commit()
    finally:
        db.close()
    result = _leak()
    assert _by_code(result, "J01")[0]["variance"] == 1000
    assert not _by_code(result, "NURSE")


def test_api_keeps_result_shape_and_dashboard_count(client):
    _pin()
    body = client.get("/api/revenue/leakage?encounter_id=enc_ipd_1").json()
    assert set(body) >= {"findings", "count", "summary"}
    assert body["count"] == len(body["findings"]) == 4
    assert set(body["findings"][0]) >= {"id", "procedure", "billing_status", "explanation", "evidence_event_ids"}
    dash = client.get("/api/dashboard?encounter_id=enc_ipd_1").json()
    assert dash["illustrative"]["leakage_identified"] == 3


def test_empty_record_has_no_findings(fresh):
    _pin(admitted=datetime(2026, 10, 20, 9, 0), discharged=datetime(2026, 10, 20, 9, 0))
    result = _leak()
    assert result["findings"] == []
    assert result["count"] == 0
    assert fresh.get("/api/revenue/leakage").json()["count"] == 0


# ---------- Medicines given ----------

def test_given_medicine_with_tariff_code_is_unbilled_until_a_bill_line_exists(fresh):
    _pin(admitted=PINNED_END)
    event_id = _given(code="B05")
    finding = _by_code(_leak(), "B05")
    assert [(f["billing_status"], f["documented_quantity"]) for f in finding] == [("unbilled", 1)]
    assert finding[0]["evidence_event_ids"] == [event_id]
    assert finding[0]["expected_amount"] == 900
    _add_line("B05", 900, docs=(event_id,))
    assert _by_code(_leak(), "B05") == []
    assert _leak()["count"] == 0


def test_medicine_that_was_held_or_refused_is_not_a_service(fresh):
    _pin(admitted=PINNED_END)
    _given(code="B05", status="held")
    _given(code="B05", status="refused")
    assert _leak()["findings"] == []


def test_given_iv_antibiotic_maps_to_j01_by_the_documented_map(client):
    _pin()
    first = _given(drug="Flucloxacillin", route="IV")
    second = _given(drug="Flucloxacillin", route="IV")
    finding = _by_code(_leak(), "J01")[0]
    assert finding["documented_quantity"] == 2
    assert finding["billed_amount"] == 3200
    assert finding["expected_amount"] == 8400
    assert finding["variance"] == 5200
    assert finding["billing_status"] == "underbilled"
    assert {first, second, "evt_seed_round"} <= set(finding["evidence_event_ids"])


def test_unmapped_medicine_is_listed_not_flagged(fresh):
    _pin(admitted=PINNED_END)
    event_id = _given(drug="Paracetamol", route="PO")
    result = _leak()
    assert result["findings"] == []
    assert result["unmapped_services"] == [
        {"label": "Paracetamol", "kind": "medication", "evidence_event_ids": [event_id]}
    ]


# ---------- Bed-days ----------

def _encounter(encounter_id, admitted, discharged, kind="IPD"):
    db = SessionLocal()
    try:
        db.add(Encounter(id=encounter_id, patient_id="pat_ravi", kind=kind, ward="W", bed="1",
                         admitted_at=admitted, discharged_at=discharged, status="closed"))
        db.commit()
    finally:
        db.close()


def test_bed_days_follow_the_encounter_dates(client):
    _encounter("enc_f13_beds", datetime(2026, 10, 10, 8, 0), datetime(2026, 10, 14, 7, 0))
    finding = _by_code(_leak("enc_f13_beds"), "ROOM2")[0]
    assert (finding["billing_status"], finding["documented_quantity"], finding["expected_amount"]) == ("unbilled", 3, 10500)
    assert finding["evidence_refs"] == [{"kind": "encounter", "id": "enc_f13_beds"}]
    _pin(datetime(2026, 10, 10, 8, 0), datetime(2026, 10, 16, 9, 0), "enc_f13_beds")
    finding = _by_code(_leak("enc_f13_beds"), "ROOM2")[0]
    assert (finding["documented_quantity"], finding["expected_amount"]) == (6, 21000)


def test_bed_day_quantity_mismatch_is_reported_in_both_directions(client):
    _encounter("enc_f13_beds", datetime(2026, 10, 10, 8, 0), datetime(2026, 10, 16, 9, 0))  # 6 days
    _add_line("ROOM2", 3 * 3500, encounter_id="enc_f13_beds", line_id="bill_f13_room")
    short = _by_code(_leak("enc_f13_beds"), "ROOM2")[0]
    assert (short["kind"], short["billing_status"]) == ("quantity_mismatch", "underbilled")
    assert (short["documented_quantity"], short["billed_quantity"], short["variance"]) == (6, 3, 10500)
    _pin(datetime(2026, 10, 10, 8, 0), datetime(2026, 10, 12, 9, 0), "enc_f13_beds")  # now 2 days, 3 billed
    extra = _by_code(_leak("enc_f13_beds"), "ROOM2")[0]
    assert (extra["kind"], extra["billing_status"]) == ("quantity_mismatch", "unsupported")
    assert (extra["documented_quantity"], extra["billed_quantity"]) == (2, 3)
    _pin(datetime(2026, 10, 10, 8, 0), datetime(2026, 10, 13, 9, 0), "enc_f13_beds")  # 3 days, 3 billed
    assert _by_code(_leak("enc_f13_beds"), "ROOM2") == []


def test_icu_bed_days_use_the_icu_code_and_a_short_stay_has_none(client):
    _encounter("enc_f13_icu", datetime(2026, 10, 10, 8, 0), datetime(2026, 10, 12, 9, 0), kind="ICU")
    finding = _by_code(_leak("enc_f13_icu"), "ICU01")[0]
    assert (finding["documented_quantity"], finding["expected_amount"]) == (2, 24000)
    assert not _by_code(_leak("enc_f13_icu"), "ROOM2")
    _encounter("enc_f13_short", datetime(2026, 10, 10, 8, 0), datetime(2026, 10, 11, 7, 59))
    assert _leak("enc_f13_short")["findings"] == []


# ---------- Matching is by code, not by text ----------

def test_description_naming_a_procedure_does_not_hide_the_unbilled_procedure(client):
    _pin()
    _add_line("ZZ99", 3500, description="Wound debridement — right lower leg")
    assert len(_by_code(_leak(), "97597", "unbilled")) == 1


def test_a_bill_line_with_the_procedure_code_clears_it_whatever_its_description(client):
    _pin()
    _add_line("97597", 3500, description="Dressing and minor care")
    assert _by_code(_leak(), "97597") == []


# ---------- Investigations and consults ----------

def test_approved_investigation_and_specialist_response_are_documented_services(fresh):
    _pin(admitted=PINNED_END)
    inv = inject_event(type="investigation_request", title="Investigation request — Renal ultrasound",
                       payload={"study": "Renal ultrasound", "request_type": "imaging", "request_id": "inv_x"},
                       source="F10", author_type="human")
    consult = inject_event(type="referral_consult", subtype="Nephrology", title="Specialist response — Nephrology",
                           payload={"referral_id": "ref_x", "status": "completed"}, source="referral",
                           author_type="human")
    result = _leak()
    us = _by_code(result, "US-RENAL")[0]
    assert (us["billing_status"], us["expected_amount"], us["evidence_event_ids"]) == ("unbilled", 2200, [inv])
    assert "not confirmed as performed" in us["explanation"]
    neph = _by_code(result, "CONS-NEPH")[0]
    assert (neph["billing_status"], neph["expected_amount"], neph["evidence_event_ids"]) == ("unbilled", 1500, [consult])


def test_seeded_sent_referral_and_request_row_are_not_findings(client):
    _pin()
    codes = {f["code"] for f in _leak()["findings"]}
    assert codes.isdisjoint({"US-RENAL", "IMG01", "CONS-NEPH", "CONS01"})


def test_superseded_event_is_not_counted_twice(fresh):
    _pin(admitted=PINNED_END)
    first = inject_event(type="procedure", title="Lab draw", payload={"procedure": "Lab draw", "code": "LAB01"},
                         source="test_feed", author_type="human")
    second = inject_event(type="procedure", title="Lab draw", payload={"procedure": "Lab draw", "code": "LAB01"},
                          source="test_feed", author_type="human", supersedes_event_id=first)
    finding = _by_code(_leak(), "LAB01")[0]
    assert finding["documented_quantity"] == 1
    assert finding["evidence_event_ids"] == [second]


# ---------- Tariff reference data ----------

def test_tariff_seed_is_idempotent_and_survives_reset(client):
    db = SessionLocal()
    try:
        db.get(TariffItem, "J01").unit_price = 1
        db.add(TariffItem(code="ZZ-F13", description="Test only", kind="procedure", unit_price=7))
        db.commit()
        upsert_tariff(db)
        upsert_tariff(db)
        db.commit()
        assert db.get(TariffItem, "J01").unit_price == 4200
        assert db.query(TariffItem).filter(TariffItem.code != "ZZ-F13").count() == len(DEFAULT_TARIFF)
    finally:
        db.close()
    assert client.post("/api/demo/reset?mode=rehearsal").status_code == 200
    db = SessionLocal()
    try:
        assert db.get(TariffItem, "ZZ-F13").unit_price == 7  # not resettable
        assert db.get(TariffItem, "97597").unit_price == 3500  # reseeded on reset
        db.delete(db.get(TariffItem, "ZZ-F13"))
        db.commit()
    finally:
        db.close()


def test_amounts_follow_the_tariff_not_a_constant(client):
    _pin()
    db = SessionLocal()
    try:
        db.get(TariffItem, "97597").unit_price = 5000
        db.commit()
    finally:
        db.close()
    try:
        assert _by_code(_leak(), "97597")[0]["expected_amount"] == 5000
    finally:
        db = SessionLocal()
        upsert_tariff(db)
        db.commit()
        db.close()


# ---------- Explanation draft ----------

def test_explanation_is_built_from_the_findings(client):
    _pin()
    leak = client.get("/api/revenue/leakage").json()
    response = client.post("/api/revenue/leakage/explain", headers=BILLING)
    assert response.status_code == 200, response.text
    content = response.json()["draft"]["content"]
    assert [(f["procedure"], f["billing_status"], f["evidence_event_ids"]) for f in content["findings"]] == [
        (f["procedure"], f["billing_status"], f["evidence_event_ids"]) for f in leak["findings"]
    ]
    assert "4 revenue findings" in content["summary"]
    assert "computed from the tariff" in content["summary"]
    assert "INR 5,700" in content["summary"]


def test_explanation_validates_with_a_quantity_mismatch_finding(client):
    _pin()
    _add_line("97597", 3500, docs=("evt_seed_procedure",), line_id="bill_f13_debr")
    inject_event(type="procedure", title="Wound debridement again", payload={"procedure": "Wound debridement"},
                 source="test_feed", author_type="human")
    leak = client.get("/api/revenue/leakage").json()
    mismatch = _by_code(leak, "97597")[0]
    assert (mismatch["kind"], mismatch["billing_status"]) == ("quantity_mismatch", "underbilled")
    assert (mismatch["documented_quantity"], mismatch["billed_quantity"]) == (2, 1)
    response = client.post("/api/revenue/leakage/explain", headers=BILLING)
    assert response.status_code == 200, response.text
    statuses = {f["procedure"]: f["billing_status"] for f in response.json()["draft"]["content"]["findings"]}
    assert statuses["Wound debridement"] == "underbilled"
