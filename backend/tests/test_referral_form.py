"""Referral dictation uses only the MediBytes six-section note."""

from __future__ import annotations

from .helpers import FakeMediBytesHTTP

SENIOR = {"X-User-Id": "u_arjun"}


def _dictate(client, monkeypatch, headers=SENIOR, note=None):
    fake = FakeMediBytesHTTP().install(monkeypatch)
    consent = client.post(
        "/api/patients/pat_ravi/consents",
        json={"consent_type": "consultation_capture", "granted": True, "note": "test"},
        headers={"X-User-Id": "u_meera"},
    )
    assert consent.status_code == 200, consent.text
    meta = client.get("/api/meta", headers=headers).json()
    note = note or {
        "present_illness": "New atrial fibrillation.",
        "examination_findings": "",
        "previous_diagnosis": "",
        "plan_of_management": "Urgent referral to Cardiology; please advise on rate control.",
        "diet_instructions": "",
        "general_instructions": "",
    }
    sent = client.post(
        f"/api/notes/transcribe?encounter_id={meta['encounter']['id']}",
        files={"file": ("r.webm", b"abc", "audio/webm")},
        data={"feature": "F11"},
        headers=headers,
    )
    assert sent.status_code == 200, sent.text
    fake.set_success(sent.json()["audio_id"], note)
    done = client.get(
        f"/api/notes/transcriptions/{sent.json()['audio_id']}?encounter_id={meta['encounter']['id']}", headers=headers
    )
    assert done.status_code == 200, done.text
    return done.json()["draft"]


def test_referral_form_leaves_fields_outside_the_six_sections_empty(client, monkeypatch):
    draft = _dictate(client, monkeypatch)
    content = draft["content"]
    assert content["format"] == "referral_v2" and content["referral_type"] == "urgent"
    assert content["department"]["text"] == "Cardiology"
    assert content["unit_chief"] is None
    assert content["header"]["name"] == "Ravi Menon" and content["header"]["hid"] == "MB-1001"
    assert "Unit chief requested of" in content["not_documented"]
    assert not any(item.get("origin") == "record" for item in content["salient_details"])


def test_approving_after_clinician_fills_the_missing_name_stores_and_queues_referral(client, monkeypatch):
    draft = _dictate(client, monkeypatch)
    changed = client.patch(f"/api/referrals/form/{draft['id']}", headers=SENIOR, json={"content": {
        "unit_chief": {"text": "Dr. Rao", "human_authored": True},
    }})
    assert changed.status_code == 200, changed.text
    done = client.post(f"/api/referrals/form/{draft['id']}/approve", headers=SENIOR)
    assert done.status_code == 200, done.text
    page = client.get(f"/api/documents/{done.json()['document_id']}/file", headers=SENIOR).text
    order = ["Name", "Sex", "Ward", "HID number", "Referral type", "Unit chief requested of", "Department",
             "Salient details", "Doctor&#x27;s name and signature", "Date and time"]
    assert [page.index(x) for x in order] == sorted(page.index(x) for x in order)
    assert "Dr. Arjun" in page and "Cardiology" in page and "Urgent (within four hours)" in page
    events = client.get("/api/patients/pat_ravi/timeline?limit=200").json()["events"]
    assert any(e["id"] == done.json()["event_id"] and e["document_id"] for e in events)
    referral = client.get("/api/referrals").json()["referrals"][0]
    assert referral["specialty"] == "Cardiology" and referral["specialist"] == "Dr. Rao" and referral["urgency"] == "urgent"


def test_a_form_with_gaps_cannot_be_approved_until_edited(client, monkeypatch):
    note = {"present_illness": "Chest pain.", "examination_findings": "", "previous_diagnosis": "",
            "plan_of_management": "", "diet_instructions": "", "general_instructions": ""}
    draft = _dictate(client, monkeypatch, note=note)
    assert "Referral type" in draft["content"]["not_documented"]
    refused = client.post(f"/api/referrals/form/{draft['id']}/approve", headers=SENIOR)
    assert refused.status_code == 400 and "Referral type" in refused.text
    edited = client.patch(f"/api/referrals/form/{draft['id']}", headers=SENIOR, json={"content": {
        "referral_type": "routine",
        "unit_chief": {"text": "Dr. Iyer", "human_authored": True},
        "department": {"text": "Neurology", "human_authored": True},
    }})
    assert edited.status_code == 200, edited.text
    assert client.post(f"/api/referrals/form/{draft['id']}/approve", headers=SENIOR).status_code == 200


def test_junior_doctors_and_nurses_cannot_refer(client, monkeypatch):
    FakeMediBytesHTTP().install(monkeypatch)
    for user in ("u_kiran", "u_anita"):
        response = client.post(
            "/api/notes/transcribe",
            files={"file": ("r.webm", b"abc", "audio/webm")},
            data={"feature": "F11"},
            headers={"X-User-Id": user},
        )
        assert response.status_code == 403
