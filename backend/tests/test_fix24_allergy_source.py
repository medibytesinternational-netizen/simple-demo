"""FIX 24: an allergy cites the allergy record event that documents it (PRD rule 3, F10 "allergies to verify")."""

from __future__ import annotations

from datetime import datetime

from tests.helpers import inject_event

GEN = "/api/investigation-requests/generate"


def _allergies(feature: str = "F10") -> list[dict]:
    """The allergies exactly as every feature reads them from the context."""
    from app.db import SessionLocal
    from app.routes.common import _state
    from app.services.context import build_context

    db = SessionLocal()
    try:
        patient, encounter, state = _state(db)
        return build_context(db, patient, encounter, state, feature)["patient"]["allergies"]
    finally:
        db.close()


def _set_patient_allergies(values: list[str]) -> None:
    from app.db import SessionLocal
    from app.models import Patient

    db = SessionLocal()
    try:
        db.get(Patient, "pat_ravi").allergies = values
        db.commit()
    finally:
        db.close()


def _record_allergy(substance: str, reaction: str) -> str:
    return inject_event(
        type="allergy_record",
        title=f"Allergy record — {substance}",
        payload={"substance": substance, "reaction": reaction, "verified": False},
        source="test_feed",
        author_type="system",
        author_name="Test feed",
        occurred_at=datetime(2026, 10, 20, 6, 0),
    )


def test_context_allergy_event_id_is_the_seeded_allergy_record_for_the_rehearsal_patient(client):
    assert _allergies() == [
        {"substance": "Penicillin — rash", "reaction": "rash", "event_id": "evt_seed_allergy"}
    ]


def test_context_allergy_keeps_its_shape_for_other_features(client):
    for feature in ("F2", "F9", "F11"):
        [item] = _allergies(feature)
        assert set(item) == {"substance", "event_id", "reaction"}
        assert item["substance"] == "Penicillin — rash"


def test_exact_substance_still_matches_its_record(client):
    _set_patient_allergies(["Penicillin"])
    assert _allergies() == [{"substance": "Penicillin", "reaction": "rash", "event_id": "evt_seed_allergy"}]


def test_substance_match_ignores_case(client):
    _set_patient_allergies(["PENICILLIN — rash"])
    assert _allergies() == [
        {"substance": "PENICILLIN — rash", "reaction": "rash", "event_id": "evt_seed_allergy"}
    ]


def test_an_allergy_with_no_record_gets_no_invented_id(client):
    _set_patient_allergies(["Penicillin — rash", "Latex — hives"])
    by_substance = {item["substance"]: item for item in _allergies()}
    assert by_substance["Penicillin — rash"]["event_id"] == "evt_seed_allergy"
    assert by_substance["Latex — hives"] == {"substance": "Latex — hives", "reaction": "", "event_id": ""}


def test_empty_record_returns_the_allergy_and_finds_its_record_once_one_exists(fresh):
    # The start record holds the allergy on the patient but no allergy record event yet.
    assert _allergies() == [{"substance": "Penicillin — rash", "reaction": "", "event_id": ""}]
    event_id = _record_allergy("Penicillin", "rash")
    assert _allergies() == [{"substance": "Penicillin — rash", "reaction": "rash", "event_id": event_id}]


def test_f10_request_cites_the_allergy_record_event(client):
    item = client.post(GEN).json()["draft"]["content"]["allergies_to_verify"][0]
    assert item == {
        "substance": "Penicillin",
        "reaction": "rash",
        "source_event_id": "evt_seed_allergy",
        "verified": False,
    }
    event = client.get(f"/api/events/{item['source_event_id']}").json()
    assert event["type"] == "allergy_record"


def test_f10_request_on_the_empty_record_cites_the_record_when_present(fresh):
    event_id = _record_allergy("Penicillin", "rash")
    item = fresh.post(GEN, json={"study": "Chest X-ray"}).json()["draft"]["content"]["allergies_to_verify"][0]
    assert (item["substance"], item["reaction"], item["source_event_id"]) == ("Penicillin", "rash", event_id)
