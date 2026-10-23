"""T1: clinical screens show Ravi only; the other four seeded patients stay as dashboard numbers.

The cohort is hidden, not deleted: seed data and the hospital dashboard are unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Patient
from app.routes import HOSPITAL_LEVEL_MODULES
from app.services import identity

COHORT = ["pat_anita", "pat_joseph", "pat_meera", "pat_arun"]
SHELL = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "Shell.tsx"

# (method, path) sampled from every clinical route module.
CLINICAL = [
    ("GET", "/api/meta"),
    ("GET", "/api/tasks"),
    ("GET", "/api/alerts"),
    ("GET", "/api/medications/reconciliation"),
    ("GET", "/api/discharge/readiness"),
    ("GET", "/api/documents"),
    ("GET", "/api/revenue/claim-prep"),
    ("GET", "/api/icu/flow-sheet"),
    ("POST", "/api/alerts/evaluate"),
    ("POST", "/api/discharge/generate"),
    ("POST", "/api/tasks"),
    ("POST", "/api/notes/generate"),
    ("POST", "/api/referrals/generate"),
    ("POST", "/api/revenue/claim-prep/prepare"),
]


def test_patient_list_is_exactly_ravi(client):
    patients = client.get("/api/patients").json()["patients"]
    assert [p["id"] for p in patients] == ["pat_ravi"]
    assert patients[0]["mrn"] == "MB-1001"


def test_browsable_allow_list_sits_beside_the_default_patient():
    assert identity.BROWSABLE_PATIENT_IDS == {"pat_ravi"}
    assert identity.DEFAULT_PATIENT_ID in identity.BROWSABLE_PATIENT_IDS


@pytest.mark.parametrize("patient_id", COHORT)
@pytest.mark.parametrize("method,path", CLINICAL)
def test_clinical_routes_refuse_a_cohort_patient_header(client, patient_id, method, path):
    response = client.request(method, path, json={} if method == "POST" else None, headers={"X-Patient-Id": patient_id})
    assert response.status_code == 403, (method, path, response.text)
    assert patient_id in response.json()["detail"]


@pytest.mark.parametrize("patient_id", COHORT)
def test_cohort_patient_paths_are_refused_with_or_without_a_header(client, patient_id):
    for suffix in ("", "/state", "/timeline", "/consents"):
        assert client.get(f"/api/patients/{patient_id}{suffix}").status_code == 403, suffix
        assert client.get(f"/api/patients/{patient_id}{suffix}", headers={"X-Patient-Id": "pat_ravi"}).status_code == 403
    assert client.post(f"/api/patients/{patient_id}/consents", json={"consent_type": "ai_processing", "granted": True}).status_code == 403


def test_ravi_still_opens_everywhere(client):
    for header in ({}, {"X-Patient-Id": "pat_ravi"}):
        assert client.get("/api/meta", headers=header).json()["patient"]["id"] == "pat_ravi"
        assert client.get("/api/patients/pat_ravi/timeline", headers=header).status_code == 200


def test_an_unknown_patient_id_is_refused_too(client):
    assert client.get("/api/meta", headers={"X-Patient-Id": "pat_nobody"}).status_code == 403


@pytest.mark.parametrize("patient_id", COHORT)
def test_hospital_level_routes_ignore_the_patient_header(client, patient_id):
    header = {"X-Patient-Id": patient_id}
    # /audit is hospital-wide too (it lives in the hospital module and lists every patient's writes).
    for path in (
        "/api/hospital/dashboard", "/api/dashboard", "/api/demo/status", "/api/audit", "/api/users", "/api/patients", "/api/credits",
    ):
        assert client.get(path, headers=header).status_code == 200, path


def test_exempt_modules_are_exactly_the_hospital_level_ones():
    assert HOSPITAL_LEVEL_MODULES == {"hospital", "platform", "integration"}


def test_dashboard_still_reports_the_five_patient_cohort(client):
    data = client.get("/api/hospital/dashboard").json()
    rows = {row["patient_id"]: row for row in data["patients"]}
    assert set(rows) == {"pat_ravi", *COHORT}
    assert data["summary"]["patients"] == 5
    assert rows["pat_ravi"]["browsable"] is True
    assert all(rows[pid]["browsable"] is False for pid in COHORT)
    assert data["summary"]["open_alerts"] == sum(row["open_alerts"] for row in rows.values())
    assert sum(row["open_alerts"] for pid, row in rows.items() if pid in COHORT) > 0


def test_cohort_patients_are_hidden_not_deleted(client):
    db = SessionLocal()
    try:
        ids = set(db.scalars(select(Patient.id)))
    finally:
        db.close()
    assert ids == {"pat_ravi", *COHORT}


@pytest.mark.parametrize("mode", ["start", "rehearsal"])
def test_demo_reset_works_in_both_modes(client, mode):
    assert client.post(f"/api/demo/reset?mode={mode}").json() == {"ok": True, "mode": mode}
    # even when a stale browser still names a cohort patient
    assert client.post(f"/api/demo/reset?mode={mode}", headers={"X-Patient-Id": "pat_joseph"}).status_code == 200
    assert [p["id"] for p in client.get("/api/patients").json()["patients"]] == ["pat_ravi"]
    rows = client.get("/api/hospital/dashboard").json()["patients"]
    assert len(rows) == (1 if mode == "start" else 5)
    client.post("/api/demo/reset?mode=rehearsal")


def test_the_header_has_no_patient_picker():
    source = SHELL.read_text()
    assert "patient-select" not in source
    assert "switchPatient" not in source
    assert '"/patients"' not in source
