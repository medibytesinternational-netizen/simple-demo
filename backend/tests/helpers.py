from __future__ import annotations

import json

from contextlib import contextmanager
from datetime import datetime
from typing import Any

ASTHMA = (
    "Doctor: Good morning, what brings you in today?\n"
    "Patient: I have had a dry cough and wheeze at night for two weeks, worse after cycling.\n"
    "Doctor: Any fever or chest pain?\n"
    "Patient: No fever. No chest pain. I use no regular medicines.\n"
    "Doctor: Your chest has scattered expiratory wheeze and peak flow is 62 percent of predicted.\n"
    "Doctor: This looks like mild persistent asthma. I will start salbutamol inhaler two puffs as needed "
    "and beclometasone 100 micrograms twice daily.\n"
    "Doctor: Review in four weeks with a peak flow diary."
)

SHORT_VISIT = "Doctor: progress review.\nPatient: feeling better today."


def texts(value: Any, out: list[str] | None = None) -> list[str]:
    """Every claim text and plain string inside a draft."""
    out = [] if out is None else out
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            out.append(value["text"])
        for key, item in value.items():
            if key != "text":
                texts(item, out)
    elif isinstance(value, list):
        for item in value:
            texts(item, out)
    elif isinstance(value, str) and len(value) > 3:
        out.append(value)
    return out


def joined(value: Any) -> str:
    return " ".join(texts(value)).lower()


def text_pdf(lines: list[str]) -> bytes:
    """A minimal one-page PDF with a real text layer."""
    stream = "BT /F1 12 Tf 50 750 Td 16 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def generate_note(client, feature: str, transcript: str) -> dict:
    response = client.post("/api/notes/generate", json={"feature": feature, "transcript": transcript})
    assert response.status_code == 200, response.text
    return response.json()["draft"]


def inject_event(**kwargs) -> str:
    """Write a timeline event as an inbound feed would (the app has no ingest route yet)."""
    from app.db import SessionLocal
    from app.services.timeline import add_event

    db = SessionLocal()
    try:
        event = add_event(
            db,
            patient_id=kwargs.pop("patient_id", "pat_ravi"),
            encounter_id=kwargs.pop("encounter_id", "enc_ipd_1"),
            **kwargs,
        )
        db.commit()
        return event.id
    finally:
        db.close()


def inject_lab(name: str, value: str, unit: str, ref: str, flag: str, at: datetime) -> str:
    return inject_event(
        type="lab_result",
        title=f"{name} — {value} {unit}",
        payload={
            "name": name, "value": value, "unit": unit, "reference_range": ref, "flag": flag,
            "review_status": "unreviewed", "collected_at": at.isoformat(),
        },
        source="test_feed",
        author_type="system",
        author_name="Test lab feed",
        occurred_at=at,
    )


def discharge(client, **approve_body) -> dict:
    draft = client.post("/api/discharge/generate").json()["draft"]
    return client.post(f"/api/drafts/{draft['id']}/approve", json=approve_body)


@contextmanager
def as_patient(patient_id: str):
    """Act on a patient through services, as the seed does.

    Clinical routes refuse non-browsable cohort patients, so tests that need a cohort record
    reach it here instead of through ``X-Patient-Id``.
    """
    from app.services import identity

    tokens = identity.set_context(None, patient_id)
    try:
        yield
    finally:
        identity.reset_context(tokens)


# ---------- a stand-in for the MediBytes pipeline API (no network) ----------

PIPELINE_TRANSCRIPT = (
    "Swelling and redness of the right leg since Tuesday. Denies fever. "
    "Pulse 104 beats per minute, the right calf is warm and tender. "
    "This looks like right leg cellulitis. Start IV cefazolin 2 g every eight hours. "
    "Get a complete blood count. Keep the leg elevated. Review in two days."
)


def _item(text, sentence, status=None):
    item = {"text": text, "source_sentence": sentence, "seg_id": 0, "confidence": 0.8}
    if status:
        item["verified_status"] = status
    return item


PIPELINE_NOTE = {
    "sections": {
        "chief_complaint": {"items": [_item("Swelling and redness of the right leg since Tuesday",
                                            "Swelling and redness of the right leg since Tuesday.")]},
        "history_of_present_illness": {"items": [_item("DENIED: fever", "Denies fever.", "verified")]},
        "past_history": {"items": []},
        "examination_general": {"items": [_item("pulse 104 beats per minute",
                                                "Pulse 104 beats per minute, the right calf is warm and tender.",
                                                "verified")]},
        "examination_systemic": {"items": [_item("right calf warm and tender",
                                                 "Pulse 104 beats per minute, the right calf is warm and tender.")]},
        "assessment": {"items": [_item("Right leg cellulitis", "This looks like right leg cellulitis.")]},
        "medications": {"items": [_item("cefazolin 2 g every eight hours",
                                        "Start IV cefazolin 2 g every eight hours.", "verified")]},
        "investigations": {"items": [_item("Complete blood count", "Get a complete blood count.", "needs_review")]},
        "plan": {"items": []},
        "advice": {"items": [_item("Keep the leg elevated", "Keep the leg elevated.")]},
        "follow_up": {"items": [_item("Review in two days", "Review in two days.", "verified")]},
    },
    "provenance": {"template": "opd", "schema": "valid"},
}


class FakePipeline:
    """Installed over app.services.pipeline's network calls by the `keyed` fixtures."""

    def __init__(self):
        self.calls = 0
        self.last_file = None
        self.error = None  # an HTTPException to raise from submit
        self.job_status = "succeeded"
        self.job_error = None
        self.note = json.loads(json.dumps(PIPELINE_NOTE))
        self.transcript = PIPELINE_TRANSCRIPT
        self.feature = None

    def submit(self, contents, filename, content_type, audio_id, feature="F1"):
        self.feature = feature
        self.calls += 1
        self.last_file = (filename, contents, content_type)
        if self.error:
            raise self.error
        return {"audio_id": audio_id, "job_id": "job-test", "status": "running"}

    def fetch(self, audio_id):
        out = {"audio_id": audio_id, "feature": self.feature or "F1",
               "job_status": self.job_status, "job_error": self.job_error}
        if self.job_status == "succeeded":
            out.update(transcript=self.transcript, note=self.note)
        return out

    def install(self, monkeypatch):
        monkeypatch.setattr("app.services.pipeline.configured", lambda: True)
        monkeypatch.setattr("app.services.pipeline.submit", self.submit)
        monkeypatch.setattr("app.services.pipeline.fetch", self.fetch)
        return self
