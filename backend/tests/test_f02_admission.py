"""F2 admission: pre-fills from records already held, flags allergies to verify (PRD F2)."""

from __future__ import annotations

from datetime import datetime

from app.services.cached.f02_admission import f2_admission_note

from .helpers import ASTHMA, SHORT_VISIT, generate_note, inject_lab

HOME_MEDICINE_IDS = {
    "evt_seed_med_metformin_home": "Metformin 1 g BD",
    "evt_seed_med_amlodipine_home": "Amlodipine 10 mg OD",
    "evt_seed_med_atorvastatin_home": "Atorvastatin 20 mg ON",
    "evt_seed_med_warfarin_home": "Warfarin 5 mg OD",
    "evt_seed_med_ibuprofen_home": "Ibuprofen 400 mg PRN",
}
ABNORMAL_LAB_IDS = {
    "evt_seed_lab_creatinine": "Creatinine",
    "evt_seed_lab_egfr": "eGFR",
    "evt_seed_lab_potassium": "Potassium",
    "evt_seed_lab_hba1c": "HbA1c",
    "evt_seed_lab_wbc": "White cell count",
    "evt_seed_lab_crp": "CRP",
}
NO_PLAN = (
    "Doctor: Good morning, what brings you in today?\n"
    "Patient: I have had a dry cough and wheeze at night for two weeks.\n"
    "Doctor: Your chest has scattered expiratory wheeze and peak flow is 62 percent of predicted."
)


def _sentences(transcript: str) -> list[str]:
    import re

    out = []
    for line in transcript.splitlines():
        spoken = line.split(":", 1)[1].strip()
        out.extend(part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", spoken) if part.strip())
    return out


def _all_claims(content: dict) -> list[dict]:
    claims = [content["chief_complaint"], content["exam"]["general"], content["exam"]["systemic"], content["history"]]
    claims += content["assessment"] + content["plan"]
    return [item for item in claims if item]


def test_admission_history_lists_home_medicines_with_their_event_ids(client):
    history = generate_note(client, "F2", ASTHMA)["content"]["history"]
    assert "Home medicines on record:" in history["text"]
    for event_id, wording in HOME_MEDICINE_IDS.items():
        assert event_id in history["source_event_ids"], event_id
        assert wording in history["text"], wording


def test_admission_history_lists_abnormal_results_with_their_event_ids(client):
    inject_lab("Sodium", "139", "mmol/L", "135 - 145", "normal", datetime(2026, 10, 19, 7, 0))
    history = generate_note(client, "F2", ASTHMA)["content"]["history"]
    assert "Abnormal latest results:" in history["text"]
    for event_id, name in ABNORMAL_LAB_IDS.items():
        assert event_id in history["source_event_ids"], event_id
        assert name in history["text"], name
    assert "Sodium" not in history["text"], "a normal result is not an abnormal one"


def test_admission_problems_are_marked_as_from_the_patient_record(client):
    history = generate_note(client, "F2", ASTHMA)["content"]["history"]
    start = history["text"].index("On the patient record:")
    line = history["text"][start:]
    assert line.startswith("On the patient record: Type 2 diabetes, Hypertension, CKD stage 3b, Atrial fibrillation.")
    # the marker line is the last piece and cites nothing of its own
    assert line.count("evt_") == 0


def test_admission_transcript_claims_are_verbatim_quotes(client):
    content = generate_note(client, "F2", ASTHMA)["content"]
    said = set(_sentences(ASTHMA))
    assert content["chief_complaint"]["text"] in said
    assert content["exam"]["general"]["text"] == (
        "Your chest has scattered expiratory wheeze and peak flow is 62 percent of predicted."
    )
    assert content["assessment"] and content["plan"]
    for item in content["assessment"] + content["plan"]:
        assert item["text"] in said, item["text"]
        assert item["source_segment_ids"] and all(seg.startswith("seg_") for seg in item["source_segment_ids"])
    patient_sentences = [s for s in _sentences(ASTHMA) if s.startswith(("I have", "No fever", "I use"))]
    for sentence in patient_sentences:
        assert sentence in content["history"]["text"], sentence
    for order in content["proposed_orders"]:
        assert order["order"] in said


def test_admission_without_a_plan_proposes_no_orders(client):
    for transcript in (SHORT_VISIT, NO_PLAN):
        content = generate_note(client, "F2", transcript)["content"]
        assert content["proposed_orders"] == []
        assert content["plan"] == []
        assert "Plan" in content["not_documented"]


def test_admission_proposed_orders_carry_their_source_sentence(client):
    draft = generate_note(client, "F2", ASTHMA)
    orders = draft["content"]["proposed_orders"]
    assert len(orders) == 1, orders
    order = orders[0]
    assert order["order"].startswith("I will start salbutamol inhaler two puffs as needed")
    assert order["rationale"] == "Said in the admission conversation"
    assert order["source_segment_ids"] == ["seg_6"]
    assert order["source_event_ids"] == [draft["content"]["plan"][0]["source_event_ids"][0]]
    assert not any("Review in four weeks" in item["order"] for item in orders), "a follow-up is not an order"


def test_admission_approval_does_not_create_an_order(client):  # said is not ordered
    draft = generate_note(client, "F2", ASTHMA)
    assert draft["content"]["proposed_orders"], "the transcript names medicines"
    before = client.get("/api/medications").json()
    substance = draft["content"]["allergies_to_verify"][0]["substance"]
    assert client.post(f"/api/drafts/{draft['id']}/verify-allergy", json={"substance": substance}).status_code == 200
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={}).status_code == 200
    after = client.get("/api/medications").json()
    assert after == before
    assert "salbutamol" not in str(after).lower()


def test_admission_allergy_source_comes_from_the_allergy_event(client):
    allergies = generate_note(client, "F2", SHORT_VISIT)["content"]["allergies_to_verify"]
    assert allergies == [
        {
            "substance": "Penicillin",
            "reaction": "rash",
            "source_event_id": "evt_seed_allergy",
            "verified": False,
        }
    ]


def test_admission_approval_before_allergy_check_is_refused(client):  # guard
    draft = generate_note(client, "F2", ASTHMA)
    refused = client.post(f"/api/drafts/{draft['id']}/approve", json={})
    assert refused.status_code == 400
    assert "allergy" in refused.text.lower()


def test_admission_on_the_empty_record_cites_no_record_events(fresh):
    content = generate_note(fresh, "F2", SHORT_VISIT)["content"]
    text = content["history"]["text"]
    for held in ("Home medicines", "Abnormal latest results", "Metformin", "eGFR", "Creatinine"):
        assert held not in text
    assert text.startswith("feeling better today.")
    transcript_event = fresh.get("/api/notes/latest?feature=F2").json()["drafts"][0]["created_from_event_ids"]
    assert content["history"]["source_event_ids"] == transcript_event
    assert content["allergies_to_verify"][0]["source_event_id"] == ""
    assert content["allergies_to_verify"][0]["verified"] is False
    assert content["proposed_orders"] == []


def test_admission_nothing_is_written_when_nothing_is_held():
    content = f2_admission_note({})
    assert content["chief_complaint"] is None
    assert content["history"] is None
    assert content["exam"] == {"general": None, "systemic": None}
    assert content["assessment"] == [] and content["plan"] == []
    assert content["proposed_orders"] == []
    assert content["allergies_to_verify"] == []
    assert content["not_documented"] == ["Presenting complaint", "History", "Examination", "Assessment", "Plan"]


def test_admission_record_only_history_cites_the_record_not_a_transcript():
    context = {
        "home_medications": [{"event_id": "evt_h1", "drug": "Metformin", "dose": "1 g", "frequency": "BD"}],
        "latest_labs": [
            {"event_id": "evt_l1", "name": "eGFR", "value": 22, "unit": "mL/min", "flag": "low"},
            {"event_id": "evt_l2", "name": "Sodium", "value": 139, "unit": "mmol/L", "flag": "normal"},
        ],
        "patient": {"problems": [], "allergies": []},
    }
    history = f2_admission_note(context)["history"]
    assert history["source_event_ids"] == ["evt_h1", "evt_l1"]
    assert history["source_segment_ids"] == []
    assert history["text"] == "Home medicines on record: Metformin 1 g BD. Abnormal latest results: eGFR 22 mL/min (low)."
