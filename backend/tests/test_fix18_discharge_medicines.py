"""A stopped medicine does not reach the discharge medication list (PRD rule 1, journey stage 4).

A doctor can stop a drug by an order or by a reconciliation decision; both leave the list.
"""

from __future__ import annotations

DOCTOR = {"X-User-Id": "u_meera"}
REASON = "Stopped after the ward round review"


def _active(client) -> list[str]:
    return [m["drug"] for m in client.get("/api/medications").json()["current_medications"]]


def _listed(client) -> dict[str, dict]:
    response = client.post("/api/discharge/generate", headers=DOCTOR)
    assert response.status_code == 200, response.text
    return {m["drug"]: m for m in response.json()["draft"]["content"]["medications"]}


def _discrepancy_for(client, drug: str) -> dict:
    items = client.get("/api/medications/reconciliation").json()["discrepancies"]
    return next(i for i in items if i["drug"] == drug and i["status"] == "open")


def test_a_drug_stopped_by_order_is_not_on_the_discharge_medication_list(client):
    before = _listed(client)
    drugs = _active(client)
    assert len(drugs) >= 2 and set(drugs) <= set(before)
    target = drugs[0]
    stop = client.post(
        "/api/medications/orders", json={"action": "stop", "drug": target, "reason": REASON}, headers=DOCTOR
    )
    assert stop.status_code == 200, stop.text
    after = _listed(client)
    assert target not in after
    assert set(after) == set(drugs) - {target}
    assert {m["status"] for m in after.values()} == {"continue"}


def test_a_drug_stopped_by_a_reconciliation_decision_is_not_on_the_list(client):
    drugs = _active(client)
    target = drugs[0]
    item = _discrepancy_for(client, target)
    resolved = client.post(
        f"/api/medications/reconciliation/{item['id']}/resolve",
        json={"decision": "stop", "note": REASON},
        headers=DOCTOR,
    )
    assert resolved.status_code == 200, resolved.text
    after = _listed(client)
    assert target not in after
    assert set(after) == set(drugs) - {target}


def test_a_continue_decision_keeps_the_drug_on_the_list(client):
    drugs = _active(client)
    target = drugs[0]
    item = _discrepancy_for(client, target)
    assert client.post(
        f"/api/medications/reconciliation/{item['id']}/resolve",
        json={"decision": "continue", "note": REASON},
        headers=DOCTOR,
    ).status_code == 200
    assert set(_listed(client)) == set(drugs)
