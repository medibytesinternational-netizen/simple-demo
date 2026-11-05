"""Staff roles. The chief doctor does everything; a senior doctor and a nurse can sign in to
work the tasks given to them (ward-round tasking), and nothing else.

``ingest`` is the one action the doctor does not hold: it belongs to the hospital system link,
which is not a person and is chosen by ``X-System-Id`` on the ingest routes only.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest

from app.db import SessionLocal, utcnow
from app.models import Task
from app.services import identity

REMOVED = ["u_dev", "u_billing", "u_mgmt", "u_hms"]
ROUTES = Path(identity.__file__).resolve().parents[1] / "routes"
SHELL = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "Shell.tsx"
NURSE_NAME = "Nurse Anita Rao"


def test_users_are_the_chief_a_senior_doctor_and_a_nurse(client):
    body = client.get("/api/users").json()
    assert [u["id"] for u in body["users"]] == ["u_meera", "u_arjun", "u_anita"]
    assert [u["role"] for u in body["users"]] == ["doctor", "senior_doctor", "nurse"]
    assert body["users"][0]["name"] == "Dr. Meera Shah"
    assert body["acting"]["id"] == "u_meera"


@pytest.mark.parametrize("user_id", [*REMOVED, "u_nobody", "sys_hms"])
def test_an_unknown_or_removed_user_id_is_rejected(client, user_id):
    headers = {"X-User-Id": user_id}
    assert 400 <= client.get("/api/meta", headers=headers).status_code < 500
    assert 400 <= client.post("/api/tasks", json={"title": "Nope"}, headers=headers).status_code < 500
    assert [t for t in client.get("/api/tasks").json()["tasks"] if t["title"] == "Nope"] == []


def test_the_doctor_holds_every_action_except_ingest(client):
    me = client.get("/api/meta").json()
    assert set(me["allowed_actions"]) == set(identity.PERMISSIONS) - {"ingest"}
    assert me["user"]["role"] == "doctor"
    roles = set().union(*identity.PERMISSIONS.values())
    assert roles == {"doctor", "senior_doctor", "nurse", identity.SYSTEM_ROLE}
    # Staff roles hold task work only.
    for role in ("senior_doctor", "nurse"):
        assert {a for a, allowed in identity.PERMISSIONS.items() if role in allowed} == {"work_task"}
    assert identity.PERMISSIONS["ingest"] == {identity.SYSTEM_ROLE}
    assert not identity.can("ingest")


def test_roles_machinery_for_billing_is_gone():
    assert not hasattr(identity, "BILLING_FEATURES")
    assert not hasattr(identity, "require_feature_role")
    for path in ROUTES.glob("*.py"):
        text = path.read_text()
        assert "require_feature_role" not in text and "BILLING_FEATURES" not in text, path.name
    assert callable(identity.require("approve_draft"))


def test_the_doctor_can_do_work_that_used_to_belong_to_other_roles(fresh):
    client = fresh
    assert client.post("/api/tasks", json={"title": "Nurse-style task"}).status_code == 200  # nurse
    assert client.post("/api/alerts/evaluate").status_code == 200  # pharmacist / integration
    assert client.post("/api/revenue/claim-prep/prepare").status_code == 200  # billing
    assert client.post("/api/credits/packs", json={"size": 15000}).status_code == 200  # billing
    ordered = client.post(
        "/api/medications/orders", json={"action": "start", "drug": "Paracetamol", "dose": "500 mg", "route": "PO", "reason": "Fever on the ward"}
    )
    assert ordered.status_code == 200, ordered.text
    given = client.post(
        f"/api/medications/orders/{ordered.json()['event']['id']}/administrations", json={"status": "given"}
    )
    assert given.status_code == 200, given.text  # nurse


def test_ingest_belongs_to_the_system_link_not_the_doctor(client):
    body = {"system": "demo-hms", "bundle": {"resourceType": "Patient"}}
    assert client.post("/api/ingest/fhir", json=body).status_code == 403
    assert client.post("/api/ingest/fhir", json=body, headers={"X-User-Id": "u_meera"}).status_code == 403
    assert client.post("/api/ingest/fhir", json=body, headers={"X-System-Id": "sys_nobody"}).status_code == 403
    # With the system actor the request passes the permission check and is judged on its body.
    assert client.post("/api/ingest/fhir", json=body, headers={"X-System-Id": "sys_hms"}).status_code == 400
    assert client.post("/api/integrations/outbox/retry").status_code == 403
    assert client.post("/api/integrations/outbox/retry", headers={"X-System-Id": "sys_hms"}).status_code == 200


def test_the_system_actor_is_not_a_selectable_user():
    assert "sys_hms" not in identity.DIRECTORY
    assert "sys_hms" in identity.SYSTEM_ACTORS
    with pytest.raises(ValueError):
        identity.set_context("sys_hms", None)


def _insert_completed(assigned_to: str) -> str:
    db = SessionLocal()
    try:
        db.merge(Task(
            id="tsk_sd_completed", patient_id="pat_ravi", encounter_id="enc_ipd_1", title="Done on the ward",
            detail="", status="completed", priority="routine", due_at=utcnow(), owner=assigned_to,
            assigned_to=assigned_to, created_by="test", escalation_level=0,
        ))
        db.commit()
    finally:
        db.close()
    return "tsk_sd_completed"


def test_assignee_names_stay_as_task_data_and_completed_by_follows_the_assignee(client):
    tid = _insert_completed(NURSE_NAME)
    row = next(t for t in client.get("/api/tasks").json()["tasks"] if t["id"] == tid)
    assert row["assigned_to"] == NURSE_NAME
    assert row["completed_by"] == NURSE_NAME
    open_task = client.post("/api/tasks", json={"title": "Open one", "owner": NURSE_NAME}).json()
    assert open_task["assigned_to"] == NURSE_NAME and open_task["completed_by"] is None


def test_overdue_escalation_still_works_with_one_role(client):
    task = client.post("/api/tasks", json={"title": "Late", "owner": NURSE_NAME, "due_in_hours": -6}).json()
    listed = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    assert listed[task["id"]]["escalation_level"] == 1
    assert client.post("/api/tasks/escalations/run").status_code == 200


def test_seeded_assignees_are_still_the_seeded_names(client):
    names = {t["assigned_to"] for t in client.get("/api/tasks").json()["tasks"]}
    assert NURSE_NAME in names


def test_the_header_offers_no_login_choice():
    source = SHELL.read_text()
    assert "user-select" not in source
    assert "Signed in as" not in source
    assert "switchUser" not in source
    assert not re.search(r'"/users"', source)
