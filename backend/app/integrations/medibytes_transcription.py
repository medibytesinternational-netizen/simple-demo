"""Server-side client for the MediBytes Transcription API."""

from __future__ import annotations

import httpx

from ..config import settings


class MediBytesRequestError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _headers() -> dict[str, str]:
    if not settings.medibytes_api_key:
        raise MediBytesRequestError(503, "MediBytes transcription is not configured (MEDIBYTES_API_KEY is missing).")
    return {"Authorization": f"Bearer {settings.medibytes_api_key}"}


async def _request(method: str, path: str, *, files=None, data=None) -> tuple[int, dict]:
    headers = _headers()
    try:
        async with httpx.AsyncClient(
            base_url=settings.medibytes_base_url.rstrip("/"),
            timeout=settings.medibytes_timeout_seconds,
        ) as client:
            response = await client.request(method, path, headers=headers, files=files, data=data)
    except httpx.TimeoutException as exc:
        raise MediBytesRequestError(504, "MediBytes transcription request timed out; check its status before retrying.") from exc
    except httpx.RequestError as exc:
        raise MediBytesRequestError(502, "Could not reach the MediBytes Transcription API.") from exc

    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    if not response.is_success:
        if response.status_code == 409:
            message = "MediBytes accepted this request only when its delivery is failed."
        elif response.status_code in {401, 403}:
            message = "MediBytes rejected the server API key; check MEDIBYTES_API_KEY."
        elif response.status_code == 404:
            message = "MediBytes has no transcription job for this audio_id."
        elif response.status_code in {400, 413, 415, 422}:
            message = f"MediBytes rejected the audio request (HTTP {response.status_code})."
        elif response.status_code == 503:
            message = "MediBytes transcription is temporarily unavailable or not configured."
        else:
            message = f"MediBytes transcription request failed (HTTP {response.status_code})."
        public_status = 502 if response.status_code in {401, 403} else response.status_code
        raise MediBytesRequestError(public_status, message)
    return response.status_code, body


async def upload_audio(audio_id: str, company_id: int, filename: str, content_type: str, audio: bytes) -> dict:
    status, body = await _request(
        "POST",
        "/api/v1/transcriptions",
        data={"audio_id": audio_id, "company_id": str(company_id)},
        files={"file": (filename, audio, content_type)},
    )
    if status != 202 or body.get("audio_id") != audio_id or not body.get("job_id"):
        raise MediBytesRequestError(502, "MediBytes returned an invalid upload acknowledgement.")
    return body


async def get_audio_status(audio_id: str) -> dict:
    _, body = await _request("GET", f"/api/v1/transcriptions/{audio_id}")
    if body.get("audio_id") != audio_id:
        raise MediBytesRequestError(502, "MediBytes returned status for a different audio_id.")
    return body


async def redeliver_transcript(audio_id: str) -> dict:
    status, body = await _request("POST", f"/api/v1/transcriptions/{audio_id}/redeliver")
    if status != 202 or body.get("audio_id") != audio_id:
        raise MediBytesRequestError(502, "MediBytes returned an invalid redelivery acknowledgement.")
    return body
