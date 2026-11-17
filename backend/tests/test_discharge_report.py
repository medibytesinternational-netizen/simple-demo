"""Discharge summary in the hospital format: generated from the record by a doctor, stored on the
timeline, viewable by every role."""

from __future__ import annotations


def test_a_doctor_generates_the_report_from_the_record(client):
    for user in ("u_arjun", "u_kiran", "u_meera"):
        r = client.post("/api/discharge/report", headers={"X-User-Id": user})
        assert r.status_code == 200, r.text
    page = client.get(f"/api/documents/{r.json()['document_id']}/file").text
    dts = ["Pain score", "Site", "Intervention if pain score is four and above", "Consultant, unit and bed",
           "Subjective", "Objective", "Vitals", "Plan", "Doctor's name, signature and registration number"]
    handoff = ["Complaints", "Vitals", "Investigations", "Medication", "Diet", "Handing over", "Taken over"]
    order = (["<span>Name", "<span>Sex", "<span>Ward", "<span>HID number", "SOAP format", "<th>Date and time",
              "<th>Progress note"] + [f"<dt>{x}</dt>" for x in dts] + ["re-document the pain score",
             "Doctors handoff communication"])
    assert [page.index(x) for x in order] == sorted(page.index(x) for x in order)
    tail = page[page.index("Doctors handoff"):]
    assert [tail.index(f"<dt>{x}</dt>") for x in handoff] == sorted(tail.index(f"<dt>{x}</dt>") for x in handoff)
    assert [page.index(x) for x in order] == sorted(page.index(x) for x in order)
    # Content comes from the record: the reason for admission, the vitals, the attending, the labs.
    assert "Right lower leg cellulitis" in page and "132/84" in page and "Ward 4B" in page
    assert "Creatinine" in page and "MB-1001" in page and "Dr. Meera Shah" in page
    events = client.get("/api/patients/pat_ravi/timeline?limit=200").json()["events"]
    assert any(e["id"] == r.json()["event_id"] and e["document_id"] for e in events)


def test_nurses_view_but_cannot_generate(client):
    client.post("/api/discharge/report")
    nurse = {"X-User-Id": "u_anita"}
    assert client.post("/api/discharge/report", headers=nurse).status_code == 403
    reports = client.get("/api/discharge/reports", headers=nurse).json()["reports"]
    assert reports and client.get(f"/api/documents/{reports[0]['document_id']}/file", headers=nurse).status_code == 200
