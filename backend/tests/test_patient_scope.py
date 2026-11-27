"""Patient scope: a record opens only for a registered patient.

Ravi is the seeded patient; anyone added through POST /patients opens too. The four-patient
cohort that used to back the dashboard was removed, so its ids are now unknown and refused.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Patient
from app.routes import HOSPITAL_LEVEL_MODULES
from app.services import identity

# Ids of the removed cohort: a stale browser may still send them.
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


def test_a_record_opens_for_registered_patients_only(client):
    assert identity.is_browsable(identity.DEFAULT_PATIENT_ID)
    assert not any(identity.is_browsable(pid) for pid in COHORT)
    assert not identity.is_browsable(None)
    new = client.post("/api/patients", json={"name": "Scope Test", "age": 40, "sex": "Male", "no_known_allergies": True}).json()
    assert identity.is_browsable(new["patient"]["id"])


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


def test_hospital_level_routes_work_whichever_patient_is_open(client):
    new = client.post("/api/patients", json={"name": "Header Test", "age": 61, "sex": "Male", "no_known_allergies": True}).json()
    for patient_id in ("pat_ravi", new["patient"]["id"]):
        header = {"X-Patient-Id": patient_id}
        # /audit is hospital-wide too (it lives in the hospital module and lists every patient's writes).
        for path in (
            "/api/hospital/dashboard", "/api/dashboard", "/api/demo/status", "/api/audit", "/api/users", "/api/patients", "/api/credits",
        ):
            assert client.get(path, headers=header).status_code == 200, (patient_id, path)


def test_exempt_modules_are_exactly_the_hospital_level_ones():
    assert HOSPITAL_LEVEL_MODULES == {"hospital", "platform", "integration"}




def test_the_seeded_cohort_is_gone(client):
    db = SessionLocal()
    try:
        ids = set(db.scalars(select(Patient.id)))
    finally:
        db.close()
    assert ids == {"pat_ravi"}
    rows = client.get("/api/hospital/dashboard").json()["patients"]
    assert [row["patient_id"] for row in rows] == ["pat_ravi"]
    assert rows[0]["browsable"] is True


@pytest.mark.parametrize("mode", ["start", "rehearsal"])
def test_demo_reset_works_in_both_modes(client, mode):
    assert client.post(f"/api/demo/reset?mode={mode}").json() == {"ok": True, "mode": mode}
    # even when a stale browser still names a cohort patient
    assert client.post(f"/api/demo/reset?mode={mode}", headers={"X-Patient-Id": "pat_joseph"}).status_code == 200
    assert [p["id"] for p in client.get("/api/patients").json()["patients"]] == ["pat_ravi"]
    rows = client.get("/api/hospital/dashboard").json()["patients"]
    assert [row["patient_id"] for row in rows] == ["pat_ravi"]
    client.post("/api/demo/reset?mode=rehearsal")


def test_the_header_has_no_patient_picker():
    source = SHELL.read_text(encoding="utf-8")
    assert "patient-select" not in source
    assert "switchPatient" not in source
    # No patient dropdown in the shell.
    assert not re.search(r"<select\b", source), "the shell renders a <select>"
    # The shell never loads the patient list (GET /patients, any quoting), the data a picker needs.
    assert not re.search(r"""\bget\s*(<[^>]*>)?\(\s*["'`]/patients(\?[^"'`]*)?["'`]""", source), "the shell fetches the patient list"
    # The shell may only clear the patient (fall back to Ravi), never set another one.
    calls = re.findall(r"session\.setPatient\(([^)]*)\)", source)
    assert all(arg.strip() == "null" for arg in calls), f"the shell sets a patient: {calls}"
