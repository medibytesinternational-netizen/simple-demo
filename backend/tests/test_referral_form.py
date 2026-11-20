"""Referral form part one: dictated by the referring doctor, filled with the patient's earlier
record, approved by the doctor, stored on the timeline as a printable form."""

from __future__ import annotations

from .helpers import FakePipeline

SENIOR = {"X-User-Id": "u_arjun"}


def _item(text):
    return {"text": text, "source_sentence": text + ".", "seg_id": 0, "confidence": 0.9}


def _dictate(client, monkeypatch, headers=SENIOR, sections=None):
    fake = FakePipeline().install(monkeypatch)
    fake.transcript = "Urgent referral to Dr. Rao in cardiology. New atrial fibrillation, please advise on rate control."
    fake.note = {"sections": sections if sections is not None else {
        "referral_type": {"items": [_item("Urgent")]},
        "unit_chief": {"items": [_item("Dr. Rao")]},
        "department": {"items": [_item("Cardiology")]},
        "salient_details": {"items": [_item("New atrial fibrillation; advice on rate control requested")]},
    }}
    sent = client.post("/api/referrals/record", files={"file": ("r.webm", b"abc", "audio/webm")}, headers=headers)
    assert sent.status_code == 200, sent.text
    assert fake.feature == "F11"
    done = client.get(f"/api/referrals/record/{sent.json()['audio_id']}", headers=headers).json()
    assert done["status"] == "succeeded", done
    return done["draft"]


def test_the_dictation_fills_the_form_and_the_record_adds_the_history(client, monkeypatch):
    c = _dictate(client, monkeypatch)["content"]
    assert c["format"] == "referral_v2" and c["referral_type"] == "urgent"
    assert c["unit_chief"]["text"] == "Dr. Rao" and c["department"]["text"] == "Cardiology"
    assert c["header"]["name"] == "Ravi Menon" and c["header"]["hid"] == "MB-1001" and c["header"]["ward"]
    origins = [d["origin"] for d in c["salient_details"]]
    assert origins[0] == "recording" and "record" in origins  # the patient's earlier content
    assert c["not_documented"] == []


def test_approving_signs_stores_and_queues_the_referral(client, monkeypatch):
    draft = _dictate(client, monkeypatch)
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
    assert referral["specialty"] == "Cardiology" and referral["urgency"] == "urgent"


def test_a_form_with_gaps_cannot_be_approved_until_edited(client, monkeypatch):
    draft = _dictate(client, monkeypatch, sections={"salient_details": {"items": [_item("Chest pain")]}})
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
    FakePipeline().install(monkeypatch)
    for user in ("u_kiran", "u_anita"):
        r = client.post("/api/referrals/record", files={"file": ("r.webm", b"abc", "audio/webm")}, headers={"X-User-Id": user})
        assert r.status_code == 403
