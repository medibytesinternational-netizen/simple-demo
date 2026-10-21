"""F16 Unified patient timeline: every event in order, with who recorded it, when and from which source.

PRD line: "Every event in order, with who recorded it, when and from which source."
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.db import SessionLocal
from app.models import TimelineEvent
from tests.helpers import ASTHMA, generate_note, inject_event

RAVI = "/api/patients/pat_ravi/timeline"
DOCTOR = "Dr. Meera Shah"
BASE = datetime(2031, 3, 1, 9, 0, 0)  # later than any seeded event, so new events lead the list


def _timeline(client, path: str = RAVI, headers: dict | None = None, **params) -> dict:
    response = client.get(path, params=params, headers=headers or {})
    assert response.status_code == 200, response.text
    return response.json()


def _ids(body: dict) -> list[str]:
    return [event["id"] for event in body["events"]]


def _write_rows(rows: list[dict]) -> None:
    db = SessionLocal()
    try:
        for row in rows:
            db.add(TimelineEvent(patient_id="pat_ravi", encounter_id="enc_ipd_1", **row))
        db.commit()
    finally:
        db.close()


def test_events_at_identical_times_come_back_in_a_stable_order(client):
    # Same occurred_at and same created_at: only the id can break the tie, newest id first.
    stamp = BASE + timedelta(days=1)
    _write_rows(
        [
            {"id": f"evt_f16_{name}", "type": "progress_note", "title": name, "source": "human",
             "author_type": "human", "author_name": "Tester", "status": "approved",
             "occurred_at": stamp, "created_at": stamp}
            for name in ("a", "b", "c")
        ]
    )
    first = _ids(_timeline(client))
    assert first[:3] == ["evt_f16_c", "evt_f16_b", "evt_f16_a"]
    assert _ids(_timeline(client)) == first


def test_same_occurred_at_is_ordered_by_created_at_then_a_newer_time_comes_first(client):
    stamp = BASE + timedelta(days=2)
    older = inject_event(type="progress_note", title="first written", occurred_at=stamp, source="human")
    newer = inject_event(type="progress_note", title="second written", occurred_at=stamp, source="human")
    latest = inject_event(type="progress_note", title="later time", occurred_at=stamp + timedelta(hours=1), source="human")
    assert _ids(_timeline(client))[:3] == [latest, newer, older]


def test_filter_by_type(client):
    labs = _timeline(client, types="lab_result")["events"]
    assert labs and {event["type"] for event in labs} == {"lab_result"}
    both = _timeline(client, types="lab_result, vitals")["events"]
    assert {event["type"] for event in both} == {"lab_result", "vitals"}
    assert len(both) > len(labs)
    assert _timeline(client, types="no_such_type")["events"] == []


def test_filter_by_source(client):
    inject_event(type="lab_result", title="K+ from the hospital", source="fhir:epic", occurred_at=BASE,
                 author_type="system", author_name="Epic feed")
    body = _timeline(client, source="fhir:epic")
    assert [event["title"] for event in body["events"]] == ["K+ from the hospital"]
    assert body["events"][0]["source_label"] == "fhir:epic"
    seeded = _timeline(client, source="seed")["events"]
    assert seeded and {event["source"] for event in seeded} == {"seed"}


def test_filter_by_date_before_after(client):
    early = inject_event(type="progress_note", title="early", occurred_at=datetime(2032, 1, 1, 8, 0), source="human")
    mid = inject_event(type="progress_note", title="mid", occurred_at=datetime(2032, 1, 2, 8, 0), source="human")
    late = inject_event(type="progress_note", title="late", occurred_at=datetime(2032, 1, 3, 8, 0), source="human")
    assert _ids(_timeline(client, after="2032-01-01"))[:3] == [late, mid, early]
    assert _ids(_timeline(client, after="2032-01-02T08:00")) == [late, mid]  # after is inclusive
    assert _ids(_timeline(client, before="2032-01-02T08:00", after="2032-01-01")) == [early]  # before is exclusive
    assert _ids(_timeline(client, before="2032-01-01"))[0] not in {early, mid, late}
    assert _ids(_timeline(client, after="2032-01-04")) == []
    # A time zone offset is converted to UTC: 13:30+05:30 is 08:00 UTC.
    assert _ids(_timeline(client, after="2032-01-02T13:30:00+05:30", before="2032-01-02T13:30:01+05:30")) == [mid]


def test_a_bad_date_is_a_clear_400(client):
    response = client.get(RAVI, params={"after": "last tuesday"})
    assert response.status_code == 400
    assert "after must be a date" in response.json()["detail"]


def test_superseding_keeps_both_visible_and_the_old_one_points_to_the_new_one(fresh):
    assert fresh.post("/api/patients/pat_ravi/consents", json={"consent_type": "consultation_capture", "granted": True}).status_code == 200
    first = generate_note(fresh, "F1", ASTHMA)
    assert fresh.post(f"/api/drafts/{first['id']}/approve", json={}).status_code == 200
    second = generate_note(fresh, "F1", ASTHMA)
    assert fresh.post(f"/api/drafts/{second['id']}/approve", json={}).status_code == 200

    notes = _timeline(fresh, types="consult_note")["events"]
    assert len(notes) == 2
    new, old = notes  # newest first
    assert old["status"] == "superseded" and new["status"] == "approved"
    assert old["superseded_by"] == new["id"]
    assert new["superseded_by"] is None
    assert new["supersedes_event_id"] == old["id"]

    detail = fresh.get(f"/api/events/{new['id']}").json()
    assert [item["id"] for item in detail["supersedes"]] == [old["id"]]
    assert detail["supersedes"][0]["status"] == "superseded"
    old_detail = fresh.get(f"/api/events/{old['id']}").json()
    assert old_detail["superseded_by"] == new["id"]
    assert old_detail["supersedes"] == []


def test_the_supersedes_chain_lists_every_earlier_version_nearest_first(client):
    v1 = inject_event(type="round_note", title="v1", occurred_at=BASE, status="superseded")
    v2 = inject_event(type="round_note", title="v2", occurred_at=BASE + timedelta(hours=1), status="superseded", supersedes_event_id=v1)
    v3 = inject_event(type="round_note", title="v3", occurred_at=BASE + timedelta(hours=2), supersedes_event_id=v2)
    detail = client.get(f"/api/events/{v3}").json()
    assert [item["id"] for item in detail["supersedes"]] == [v2, v1]
    assert client.get(f"/api/events/{v1}").json()["superseded_by"] == v2


def test_every_event_has_who_when_and_source(client):
    inject_event(type="lab_result", title="from a feed", source="fhir:cerner", author_type="system", author_name="Cerner feed", occurred_at=BASE)
    inject_event(type="note", title="odd source", source="front_desk_import", author_type="human", author_name="Clerk", occurred_at=BASE)
    events = _timeline(client, limit=500)["events"]
    assert len(events) > 20
    for event in events:
        assert isinstance(event["recorded_by"], str) and event["recorded_by"].strip(), event["id"]
        assert isinstance(event["occurred_at"], str) and event["occurred_at"].strip(), event["id"]
        assert isinstance(event["source"], str) and event["source"].strip(), event["id"]
        assert isinstance(event["source_label"], str) and event["source_label"].strip(), event["id"]
    by_title = {event["title"]: event for event in events}
    assert by_title["from a feed"]["source_label"] == "fhir:cerner"
    assert by_title["odd source"]["source_label"] == "Front desk import"
    # The labels the PRD page promises.
    inject_event(type="consult_note", title="label check", source="F1", occurred_at=BASE)
    inject_event(type="lab_result", title="scan check", source="lab", occurred_at=BASE)
    again = {event["title"]: event for event in _timeline(client)["events"]}
    assert again["label check"]["source_label"] == "Consultation note draft"
    assert again["scan check"]["source_label"] == "Lab report scan"


def test_another_patients_events_never_appear(client):
    mine = inject_event(type="progress_note", title="Ravi only", occurred_at=BASE, source="human")
    theirs = inject_event(patient_id="pat_anita", encounter_id=None, type="progress_note", title="Anita only", occurred_at=BASE, source="human")
    for header in ({}, {"X-Patient-Id": "pat_ravi"}, {"X-Patient-Id": "pat_anita"}):
        ravi = _timeline(client, headers=header)
        assert mine in _ids(ravi) and theirs not in _ids(ravi)
        assert {event["patient_id"] for event in ravi["events"]} == {"pat_ravi"}
        anita = _timeline(client, "/api/patients/pat_anita/timeline", headers=header)
        assert theirs in _ids(anita) and mine not in _ids(anita)
        assert {event["patient_id"] for event in anita["events"]} == {"pat_anita"}
    # The drawer follows the same rule: an event of another patient is not served.
    response = client.get(f"/api/events/{theirs}", headers={"X-Patient-Id": "pat_ravi"})
    assert response.status_code == 400 and "another patient" in response.json()["detail"]
    assert client.get(f"/api/events/{theirs}", headers={"X-Patient-Id": "pat_anita"}).status_code == 200


def test_model_and_human_events_display_differently(client):
    model_id = inject_event(type="consult_note", title="AI note", source="F1", author_type="model",
                            author_name="gpt-test (f1.v2)", approved_by=DOCTOR, occurred_at=BASE)
    human_id = inject_event(type="progress_note", title="Typed note", source="human", author_type="human",
                            author_name="Nurse Anita Rao", occurred_at=BASE)
    by_id = {event["id"]: event for event in _timeline(client)["events"]}
    model, human = by_id[model_id], by_id[human_id]
    assert model["ai_drafted"] is True and human["ai_drafted"] is False
    assert model["drafted_by"] == "gpt-test (f1.v2)" and human["drafted_by"] is None
    assert model["approved_by"] == DOCTOR
    assert model["recorded_by"] == DOCTOR and human["recorded_by"] == "Nurse Anita Rao"
    assert model["authorship"] == f"Drafted by gpt-test (f1.v2), approved by {DOCTOR}"
    assert human["authorship"] == "Recorded by Nurse Anita Rao"
    # The detail route says the same.
    assert client.get(f"/api/events/{model_id}").json()["authorship"] == model["authorship"]


def test_a_model_event_with_no_approver_is_not_shown_as_approved(client):
    event_id = inject_event(type="consult_note", title="Unsigned", source="F1", author_type="model",
                            author_name="gpt-test (f1.v2)", approved_by=None, occurred_at=BASE)
    event = client.get(f"/api/events/{event_id}").json()
    assert event["authorship"] == "Drafted by gpt-test (f1.v2), not yet approved"
    assert event["approved_by"] is None


def test_unknown_event_id_is_a_clear_400(client):
    response = client.get("/api/events/evt_does_not_exist")
    assert response.status_code == 400
    assert response.json()["detail"] == "Event not found"


def test_facets_ignore_the_filters(client):
    everything = _timeline(client)["facets"]
    filtered = _timeline(client, types="vitals", source="seed")
    assert filtered["facets"] == everything
    assert {"vitals", "lab_result"} <= set(everything["types"])
    assert {"source": "seed", "label": "Demo seed data"} in everything["sources"]
    assert filtered["filters"]["types"] == ["vitals"]


def test_unapproved_and_rejected_events_never_appear(client):
    hidden = inject_event(type="progress_note", title="not signed", status="draft", occurred_at=BASE, source="human")
    assert hidden not in _ids(_timeline(client, limit=500))
