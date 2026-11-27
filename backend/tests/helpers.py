from __future__ import annotations

import json
from email import policy
from email.parser import BytesParser

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import httpx

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


class FakeMediBytesHTTP:
    """Fake the upstream HTTP service while exercising the real client adapter and routes."""

    BASE = "https://product-production-b091.up.railway.app"

    def __init__(self, *, api_key: str = "mb-test-key", company_id: int = 7, callback_token: str = "callback-test-token"):
        self.calls: list[tuple[str, int, str, str, bytes]] = []
        self.statuses: dict[str, dict[str, Any]] = {}
        self.failure_status: int | None = None
        self.network_error = False
        self.settings = SimpleNamespace(
            medibytes_api_key=api_key,
            medibytes_callback_token=callback_token,
            medibytes_company_id=company_id,
            medibytes_base_url=self.BASE,
            medibytes_timeout_seconds=90,
        )
        self.callback_settings = SimpleNamespace(medibytes_callback_token=callback_token)

    def set_success(self, audio_id: str, note: dict[str, str], needs_review: list[dict[str, str]] | None = None) -> None:
        self.statuses[audio_id].update(
            job_status="succeeded",
            response=json.dumps([note], ensure_ascii=False, separators=(",", ":")),
            needs_review=needs_review or [],
        )

    def _multipart(self, request: httpx.Request) -> dict[str, tuple[str | None, str, bytes]]:
        headers = f"Content-Type: {request.headers['content-type']}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        message = BytesParser(policy=policy.default).parsebytes(headers + request.content)
        fields = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name:
                fields[name] = (part.get_filename(), part.get_content_type(), part.get_payload(decode=True) or b"")
        return fields

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.network_error:
            raise httpx.ConnectError("simulated connection failure", request=request)
        if self.failure_status:
            return httpx.Response(self.failure_status, request=request)
        path = request.url.path
        if path == "/api/v1/transcriptions" and request.method == "POST":
            fields = self._multipart(request)
            audio_id = fields["audio_id"][2].decode()
            company_id = int(fields["company_id"][2].decode())
            filename, content_type, audio = fields["file"]
            self.calls.append((audio_id, company_id, filename or "", content_type, audio))
            self.statuses.setdefault(audio_id, {
                "audio_id": audio_id,
                "company_id": company_id,
                "job_id": f"job-{audio_id}",
                "job_status": "queued",
                "job_error": None,
                "delivery": {"state": "pending", "attempts": 0, "last_http_status": None, "last_error": None,
                             "hims_reply": None, "delivered_at": None, "next_attempt_at": None},
                "response": None,
                "needs_review": [],
            })
            return httpx.Response(202, json={"audio_id": audio_id, "company_id": company_id,
                                             "job_id": f"job-{audio_id}", "status": "queued"}, request=request)
        if path.startswith("/api/v1/transcriptions/"):
            tail = path.removeprefix("/api/v1/transcriptions/")
            redeliver = tail.endswith("/redeliver")
            audio_id = tail.removesuffix("/redeliver") if redeliver else tail
            payload = self.statuses.get(audio_id)
            if payload is None:
                return httpx.Response(404, json={"detail": "not found"}, request=request)
            if redeliver and request.method == "POST":
                if payload["delivery"]["state"] != "failed":
                    return httpx.Response(409, json={"detail": "not failed"}, request=request)
                payload["delivery"]["state"] = "pending"
                return httpx.Response(202, json={"audio_id": audio_id, "status": "accepted"}, request=request)
            if request.method == "GET" and not redeliver:
                return httpx.Response(200, json=payload, request=request)
        return httpx.Response(404, json={"detail": "not found"}, request=request)

    def install(self, monkeypatch):
        monkeypatch.setattr("app.services.transcription.settings", self.settings)
        monkeypatch.setattr("app.integrations.medibytes_transcription.settings", self.settings)
        monkeypatch.setattr("app.routes.notes.settings", self.callback_settings)
        real_client = httpx.AsyncClient
        transport = httpx.MockTransport(self._handle)
        monkeypatch.setattr(
            "app.integrations.medibytes_transcription.httpx.AsyncClient",
            lambda **kwargs: real_client(transport=transport, **kwargs),
        )
        return self
