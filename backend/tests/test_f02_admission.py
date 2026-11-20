"""F2 admission note in the hospital admission format.

Record headings come from the record; the rest from the admission dictation, quoted as said. A
heading the dictation does not mention is filled from the signed OPD report (recording wins).
Allergies must be verified by the doctor. Signing never places an order; it admits an OPD patient.
"""

from __future__ import annotations

from app.services.cached.f02_admission import f2_admission_note

from .helpers import ASTHMA, SHORT_VISIT, generate_note

ADMIT = (
    "Doctor: We are admitting her as an emergency.\n"
    "Doctor: Please admit her to the medical ward.\n"
    "Doctor: She will be under general medicine.\n"
    "Doctor: The provisional diagnosis is community acquired pneumonia.\n"
    "Doctor: Start IV ceftriaxone 1 g twice daily.\n"
    "Doctor: I expect her to improve within a few days.\n"
    "Doctor: There is a risk of sepsis.\n"
    "Doctor: This is under the insurance category.\n"
    "Doctor: Send a complete blood count and blood cultures.\n"
    "Doctor: Get a chest x-ray today.\n"
    "Doctor: We need a pulmonology opinion."
)
NEW = {"name": "Kamala Devi", "age": 63, "sex": "Female", "allergies": ["Sulfa drugs - rash"]}


def _claims(value, out=None):
    out = [] if out is None else out
    if isinstance(value, dict):
        if isinstance(value.get("text"), str) and "source_segment_ids" in value:
            out.append(value)
        for item in value.values():
            _claims(item, out)
    elif isinstance(value, list):
        for item in value:
            _claims(item, out)
    return out


def _new_patient_with_opd(client, opd_said: str | None = None, name: str = "Kamala Devi") -> str:
    r = client.post("/api/patients", json={**NEW, "name": name})
    assert r.status_code == 200, r.text
    pid = r.json()["patient"]["id"]
    h = {"X-Patient-Id": pid}
    client.post(f"/api/patients/{pid}/consents", json={"consent_type": "consultation_capture", "granted": True, "note": "t"}, headers=h)
    if opd_said:
        d = client.post("/api/notes/generate", json={"feature": "F1", "transcript": opd_said}, headers=h).json()["draft"]
        assert client.post(f"/api/drafts/{d['id']}/approve", json={}, headers=h).status_code == 200
    return pid


def _admit(client, pid: str, said: str = ADMIT) -> dict:
    r = client.post("/api/notes/generate", json={"feature": "F2", "transcript": said}, headers={"X-Patient-Id": pid})
    assert r.status_code == 200, r.text
    return r.json()["draft"]


def test_admission_fills_the_hospital_format_from_what_was_said(client):
    pid = _new_patient_with_opd(client)
    c = _admit(client, pid)["content"]
    assert c["format"] == "admit_v2"
    assert "emergency" in c["admission_type"]["text"]
    assert "medical ward" in c["ward"]["text"]
    assert "general medicine" in c["speciality"]["text"]
    assert "pneumonia" in c["provisional_diagnosis"][0]["text"]
    assert "ceftriaxone" in c["proposed_treatment"][0]["text"]
    assert "improve" in c["expected_outcome"]["text"]
    assert "sepsis" in c["possible_complications"][0]["text"]
    assert "insurance" in c["cost_category"]["text"]
    assert "blood count" in c["admission_labs"][0]["text"]
    assert "x-ray" in c["imaging_studies"][0]["text"]
    assert "pulmonology" in c["consultations_required"][0]["text"]
    h = c["header"]
    assert (h["name"], h["sex"], h["age"]) == ("Kamala Devi", "Female", "63 years")
    assert h["op_number"].startswith("MB-") and h["consultant"] == "Dr. Meera Shah"
    for claim in _claims(c):
        assert claim["text"] in ADMIT and claim["origin"] == "recording"


def test_the_signed_opd_report_fills_what_the_dictation_did_not_say(client):
    pid = _new_patient_with_opd(client, "Patient: I am allergic to penicillin, it gives me a rash.\nDoctor: Noted.")
    c = _admit(client, pid)["content"]
    opd = [a for a in c["allergies"] if a.get("origin") == "opd"]
    assert opd and "penicillin" in opd[0]["text"]
    assert opd[0]["source_segment_ids"] == []  # it cites the OPD report itself, not this dictation
    # The recording wins: a heading the dictation filled is never replaced from the OPD report.
    said = ADMIT + "\nDoctor: She is allergic to aspirin."
    c2 = _admit(client, _new_patient_with_opd(client, "Patient: I am allergic to penicillin.\nDoctor: Noted.", "Lalitha Rao"), said)["content"]
    assert [a["origin"] for a in c2["allergies"]] == ["recording"] and "aspirin" in c2["allergies"][0]["text"]


def test_every_allergy_must_be_verified_before_signing(client):
    pid = _new_patient_with_opd(client)
    h = {"X-Patient-Id": pid}
    draft = _admit(client, pid)
    substances = [a["substance"] for a in draft["content"]["allergies_to_verify"]]
    assert substances == ["Sulfa drugs"]
    refused = client.post(f"/api/drafts/{draft['id']}/approve", json={}, headers=h)
    assert refused.status_code == 400 and "allergy" in refused.text.lower()


def test_signing_admits_an_opd_patient_to_the_ward_said_and_places_no_order(client):
    pid = _new_patient_with_opd(client)
    h = {"X-Patient-Id": pid}
    draft = _admit(client, pid)
    before = client.get("/api/medications", headers=h).json()
    assert client.post(f"/api/drafts/{draft['id']}/verify-allergy", json={"substance": "Sulfa drugs"}, headers=h).status_code == 200
    signed = client.post(f"/api/drafts/{draft['id']}/approve", json={}, headers=h)
    assert signed.status_code == 200, signed.text
    meta = client.get("/api/meta", headers=h).json()
    assert meta["encounter"]["kind"] == "IPD" and "medical ward" in meta["encounter"]["ward"]
    assert meta["encounter"]["status"] == "active"
    types = [e["type"] for e in client.get(f"/api/patients/{pid}/timeline?limit=100", headers=h).json()["events"]]
    assert "admission_note" in types and "admission" in types
    assert signed.json()["event"]["payload"]["header"]["date_of_admission"]
    # Proposed treatment is a proposal: no medicine order was created.
    assert "ceftriaxone" not in str(client.get("/api/medications", headers=h).json()).lower()
    assert client.get("/api/medications", headers=h).json().keys() == before.keys()


def test_an_inpatient_is_not_admitted_twice(client):
    # Ravi is already an inpatient; signing an admission note for him opens no new visit.
    draft = generate_note(client, "F2", ASTHMA)
    enc_before = client.get("/api/meta").json()["encounter"]["id"]
    for item in draft["content"]["allergies_to_verify"]:
        client.post(f"/api/drafts/{draft['id']}/verify-allergy", json={"substance": item["substance"]})
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={}).status_code == 200
    assert client.get("/api/meta").json()["encounter"]["id"] == enc_before


def test_admission_allergy_source_comes_from_the_allergy_event(client):
    allergies = generate_note(client, "F2", SHORT_VISIT)["content"]["allergies_to_verify"]
    assert allergies == [{"substance": "Penicillin", "reaction": "rash", "source_event_id": "evt_seed_allergy", "verified": False}]


def test_nothing_is_written_when_nothing_was_said():
    content = f2_admission_note({})
    assert content["format"] == "admit_v2"
    assert all(not v for k, v in content.items() if k != "format")


def test_an_admission_recording_becomes_an_admission_draft(client, monkeypatch):
    from .helpers import FakePipeline

    fake = FakePipeline().install(monkeypatch)
    fake.transcript = "We are admitting him as an emergency. Please admit him to Ward 5. Get a chest x-ray."
    item = lambda text, sentence: {"text": text, "source_sentence": sentence, "seg_id": 0, "confidence": 0.8}
    fake.note = {"sections": {
        "admission_type": {"items": [item("Emergency", "We are admitting him as an emergency.")]},
        "ward": {"items": [item("Ward 5", "Please admit him to Ward 5.")]},
        "imaging_studies": {"items": [item("Chest x-ray", "Get a chest x-ray.")]},
    }}
    pid = _new_patient_with_opd(client, name="Ramesh Gupta")
    h = {"X-Patient-Id": pid}
    sent = client.post("/api/notes/transcribe", files={"file": ("admit.webm", b"abc", "audio/webm")}, data={"feature": "F2"}, headers=h)
    assert sent.status_code == 200, sent.text
    assert fake.feature == "F2"
    done = client.get(f"/api/notes/transcribe/{sent.json()['audio_id']}", headers=h).json()
    assert done["status"] == "succeeded", done
    c = done["draft"]["content"]
    assert done["draft"]["feature"] == "F2" and c["format"] == "admit_v2"
    assert c["ward"]["text"] == "Ward 5" and c["imaging_studies"][0]["text"] == "Chest x-ray"
    assert "Provisional diagnosis" in c["not_documented"]


def test_the_signed_admission_note_is_stored_and_opens_from_the_timeline(client):
    pid = _new_patient_with_opd(client, name="Suresh Kumar")
    h = {"X-Patient-Id": pid}
    draft = _admit(client, pid, ADMIT + "\nDoctor: Note <script>x</script> on the ward.")
    client.post(f"/api/drafts/{draft['id']}/verify-allergy", json={"substance": "Sulfa drugs"}, headers=h)
    event = client.post(f"/api/drafts/{draft['id']}/approve", json={}, headers=h).json()["event"]
    assert event["document_id"]
    page = client.get(f"/api/documents/{event['document_id']}/file", headers=h).text
    assert "Admission note" in page and "Suresh Kumar" in page and "Signed by Dr. Meera Shah" in page
    order = ["Name", "Sex", "Age", "OP number", "On (date of admission)", "Under (consultant)", "Elective or emergency",
             "Admit to ward", "Speciality", "Provisional diagnosis", "Proposed treatment", "Expected outcome",
             "Possible complications", "Allergies", "Approximate cost or category", "Admission labs",
             "Imaging studies", "Consultations required"]
    positions = [page.index(label) for label in order]
    assert positions == sorted(positions)
    assert "<script>x</script>" not in page
    # Still on the timeline after admission (the note is on the closed OPD visit).
    timeline = client.get(f"/api/patients/{pid}/timeline?limit=100", headers=h).json()["events"]
    assert any(e["id"] == event["id"] and e["document_id"] for e in timeline)
