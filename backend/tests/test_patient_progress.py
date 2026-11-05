"""Patient progress: overall (OPD to discharge) and daily (tasks and notes for one day)."""

from __future__ import annotations

URL = "/api/patients/pat_ravi/progress"
NURSE = {"X-User-Id": "u_anita"}


def _checks(body) -> dict[str, dict]:
    return {c["key"]: c for stage in body["overall"]["stages"] for c in stage["checks"]}


def test_a_fresh_record_shows_the_stay_as_not_started(fresh):
    body = fresh.get(URL).json()
    checks = _checks(body)
    assert checks["consult_note"]["status"] == "missing"
    assert checks["admission_note"]["status"] == "missing"
    assert checks["discharge_summary"]["status"] == "missing"
    assert [s["key"] for s in body["overall"]["stages"]][0] == "opd"
    assert [s["key"] for s in body["overall"]["stages"]][-1] == "discharge"


def test_rehearsal_record_mixes_done_and_pending(client):
    body = client.get(URL).json()
    checks = _checks(body)
    assert checks["consult_note"]["status"] == "done"
    assert checks["round_note"]["status"] == "done"
    assert checks["alerts"]["status"] == "pending"
    assert checks["tasks"]["status"] == "pending"
    overall = body["overall"]
    assert 0 < overall["percent"] < 100
    assert overall["done"] < overall["total"]


def test_an_unconfirmed_outside_report_keeps_documents_pending(client):
    state = client.get("/api/patients/pat_ravi/state").json()
    waiting = [d for d in state["documents"] if d["ocr_status"] in {"needs_confirmation", "pending", "needs_manual_entry"}]
    expected = "pending" if waiting else "done"
    assert _checks(client.get(URL).json())["documents"]["status"] == expected


def test_a_completed_task_counts_in_that_days_progress(client):
    task = client.post("/api/tasks", json={"title": "Dress the wound", "owner": "Nurse Anita Rao", "due_in_hours": 1}).json()
    day = task["due_at"][:10]
    before = client.get(URL, params={"date": day}).json()["daily"]
    row = next(t for t in before["tasks"] if t["id"] == task["id"])
    assert row["state"] in {"open", "overdue"}

    assert client.post(f"/api/tasks/{task['id']}/acknowledge", headers=NURSE).status_code == 200
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"}, headers=NURSE).status_code == 200

    after = client.get(URL, params={"date": day}).json()["daily"]
    assert next(t for t in after["tasks"] if t["id"] == task["id"])["state"] == "done"
    assert after["tasks_done"] == before["tasks_done"] + 1
    # The finished task is written to the chart, so it is a verified record for the day too.
    assert any(n["kind"] == "Completed task" and n["state"] == "verified" for n in after["notes"])


def test_days_cover_the_stay_and_a_bad_date_is_refused(client):
    body = client.get(URL).json()
    assert body["days"] and body["days"] == sorted(body["days"])
    assert client.get(URL, params={"date": "not-a-date"}).status_code == 400
