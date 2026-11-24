from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.integrations import medibytes_transcription as client

BASE = "https://product-production-b091.up.railway.app"


def _settings(monkeypatch):
    monkeypatch.setattr(
        client,
        "settings",
        SimpleNamespace(
            medibytes_api_key="server-only-test-key",
            medibytes_base_url=BASE,
            medibytes_timeout_seconds=90,
        ),
    )


def test_upload_uses_documented_bearer_multipart_fields_and_audio_id(monkeypatch):
    _settings(monkeypatch)
    captured = []
    audio_id = "visit-1"

    def handler(request):
        captured.append(request)
        return httpx.Response(202, json={"audio_id": audio_id, "company_id": 1, "job_id": "job-1", "status": "queued", "status_url": f"/api/v1/transcriptions/{audio_id}"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    response = asyncio.run(client.upload_audio(audio_id, 1, "consultation.wav", "audio/wav", b"audio-bytes"))

    request = captured[0]
    body = request.content.decode("latin-1")
    assert response["job_id"] == "job-1"
    assert request.method == "POST" and str(request.url) == f"{BASE}/api/v1/transcriptions"
    assert request.headers["authorization"] == "Bearer server-only-test-key"
    assert "name=\"audio_id\"" in body and "visit-1" in body
    assert 'name="company_id"\r\n\r\n1' in body
    assert 'name="file"; filename="consultation.wav"' in body
    assert "audio-bytes" in body


def test_status_and_redelivery_use_only_documented_paths(monkeypatch):
    _settings(monkeypatch)
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.method == "GET":
            return httpx.Response(200, json={"audio_id": "visit-2", "job_status": "succeeded", "delivery": {"state": "failed"}, "response": "recognized words"})
        return httpx.Response(202, json={"audio_id": "visit-2", "status": "accepted"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    status = asyncio.run(client.get_audio_status("visit-2"))
    redeliver = asyncio.run(client.redeliver_transcript("visit-2"))
    assert status["response"] == "recognized words"
    assert redeliver["status"] == "accepted"
    assert calls == [
        ("GET", "/api/v1/transcriptions/visit-2", "Bearer server-only-test-key"),
        ("POST", "/api/v1/transcriptions/visit-2/redeliver", "Bearer server-only-test-key"),
    ]


def test_api_key_rejection_is_reported_as_upstream_configuration_error(monkeypatch):
    _settings(monkeypatch)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        client.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(lambda _request: httpx.Response(401)), **kwargs),
    )
    with pytest.raises(client.MediBytesRequestError) as failure:
        asyncio.run(client.get_audio_status("visit-3"))
    assert failure.value.status_code == 502
    assert "MEDIBYTES_API_KEY" in str(failure.value)
    assert "server-only-test-key" not in str(failure.value)


def test_network_timeout_has_a_retryable_timeout_status(monkeypatch):
    _settings(monkeypatch)
    real_client = httpx.AsyncClient

    def timeout(_request):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(timeout), **kwargs))
    with pytest.raises(client.MediBytesRequestError) as failure:
        asyncio.run(client.get_audio_status("visit-4"))
    assert failure.value.status_code == 504
    assert "check its status" in str(failure.value)
