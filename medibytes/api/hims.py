"""The hospital (HIMS) side: the six-field note and its delivery to their receive API.

    POST <MEDIBYTES_HIMS_URL>   Authorization: Bearer <MEDIBYTES_HIMS_TOKEN>
    {"audio_id": "...", "company_id": 1, "response": "[{\"present_illness\": \"...\", ...}]"}

`response` is a *string* holding a JSON array of one object with six string fields.

Their API reports failure in the body, not the status: a bad token answers HTTP 200 with
{"status":"Failed","Message":"Unauthorized"} (probed 2026-10-22). So a 2xx only counts as
delivered when the body does not say "Failed". It has no failure channel in the other
direction, so a recording we cannot process is never pushed: the state is `job_failed`
and the hospital reads it from our status route.

One JSON file per audio_id under <runs>/hims/ is the whole delivery state, so a restart
loses nothing. A single worker thread scans for deliveries that are due; there is no
in-memory queue to rebuild.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..extraction.negation import sentence_negated
from .jobs import JobService

log = logging.getLogger(__name__)

SECTIONS = ("present_illness", "examination_findings", "previous_diagnosis",
            "plan_of_management", "diet_instructions", "general_instructions")
AUDIO_ID_PATTERN = r"^[A-Za-z0-9-]{1,64}$"
_AUDIO_ID = re.compile(AUDIO_ID_PATTERN)
SEND_TIMEOUT_S = 30
_BODY_LIMIT = 64 * 1024


# ---- the note -------------------------------------------------------------------------


_DENIED_SYMPTOM = re.compile(r"^DENIED:\s*", re.I)
_NO_DOSE = re.compile(r"\s+no dose$", re.I)
_ALBUTEROL = re.compile(r"\balbuterol\b", re.I)  # the reference list is US-named; Indian wards say salbutamol
_VITAL_LABEL = re.compile(r"^(pulse|heart rate|temperature|respiratory rate|blood pressure|saturation|spo2)\b", re.I)
_VITAL_UNIT = re.compile(r"beats|breaths|per minute|bpm|degrees|mmhg|%", re.I)


_RESTARTED_VITAL = re.compile(
    r"^(pulse|heart rate|respiratory rate|temperature|saturation|spo2)(\s+)\d+(?:\.\d+)?\s*,?\s+(?=\d)", re.I)


def _clean(text: str) -> str:
    """The pipeline's internal wording, as a clinician would write it: "DENIED: fever" is
    "Denies fever", the "no dose" label of a drug heard without a dose is dropped, the US name
    albuterol is the international salbutamol, and a one-valued vital heard as two numbers
    ("pulse 100, 104 beats per minute") keeps the last: the first was a restart."""
    text = _NO_DOSE.sub("", " ".join(text.split()))
    text = _RESTARTED_VITAL.sub(r"\1\2", text)
    text = _DENIED_SYMPTOM.sub("Denies ", text)
    return _ALBUTEROL.sub(lambda m: "Salbutamol" if m.group()[0].isupper() else "salbutamol", text)


def _resolve_vital_conflicts(texts: list[str]) -> list[str]:
    """One vital read twice ("pulse 100, 104 beats per minute" is a restart): when exactly one
    reading carries its unit it is the complete one, so keep it. Otherwise there is nothing to
    choose by, and both stay."""
    groups: dict[str, list[str]] = {}
    for text in texts:
        if m := _VITAL_LABEL.match(text):
            groups.setdefault(m.group(1).lower(), []).append(text)
    drop = set()
    for group in groups.values():
        with_unit = [t for t in group if _VITAL_UNIT.search(t)]
        if len(group) > 1 and len(with_unit) == 1:
            drop |= set(group) - set(with_unit)
    return [t for t in texts if t not in drop]


def _contains(short: str, long: str) -> bool:
    return re.search(rf"\b{re.escape(short)}\b", long) is not None


def _dedupe(texts: list[str]) -> list[str]:
    """Drop an item that a longer item of the same section already says ("fever" inside
    "three days of fever"), and exact repeats. An affirmed finding is kept when the longer
    item is negated and it is not: "chest pain" is not "no radiation of chest pain"."""
    texts = [t for t in (" ".join(t.split()) for t in texts) if t]
    kept: list[str] = []
    for i, text in enumerate(texts):
        low = text.lower()
        swallowed = any(
            j != i and low != other.lower() and _contains(low, other.lower())
            and not (sentence_negated(other) and not sentence_negated(text))
            for j, other in enumerate(texts))
        if not swallowed and low not in {k.lower() for k in kept}:
            kept.append(text)
    return kept


def format_response(discharge: Mapping[str, Any]) -> str:
    """The `response` field: a JSON array of one object with the six sections as strings."""
    prov = discharge.get("provenance") or {}
    engine = str(prov.get("llm_engine", ""))
    if engine.startswith("discharge-skipped"):
        # The pipeline degrades instead of failing, so such a job "succeeds" with six empty
        # sections. Pushed, that blank would read as a real (empty) note.
        raise ValueError(f"the discharge note was not written ({engine}); upload the recording "
                         f"again once the cause is fixed")
    if prov.get("schema") == "INVALID":
        raise ValueError(f"the discharge note failed its schema check: {prov.get('schema_error', '')}")
    sections = discharge.get("sections") or {}
    row = {}
    for s in SECTIONS:
        texts = [_clean(str(i.get("text", ""))) for i in ((sections.get(s) or {}).get("items") or [])]
        if s == "examination_findings":
            texts = _resolve_vital_conflicts(texts)
        row[s] = "; ".join(_dedupe(texts))
    return json.dumps([row], ensure_ascii=False)


def needs_review(discharge: Mapping[str, Any]) -> list[dict[str, str]]:
    """Items the pipeline could not fully prove. The plain-string response cannot carry the
    flag, so the status route lists them for whoever checks the note."""
    sections = discharge.get("sections") or {}
    return [{"section": s, "text": str(i.get("text", ""))}
            for s in SECTIONS for i in ((sections.get(s) or {}).get("items") or [])
            if i.get("verified_status") == "needs_review"]


# ---- their reply -----------------------------------------------------------------------


def classify(status: int, headers: Mapping[str, str], text: str) -> tuple[str, str]:
    """(`delivered` | `retry` | `failed`, message) for one HTTP reply from HIMS."""
    snippet = " ".join(text.split())[:300]
    if headers.get("cf-mitigated") or "just a moment" in text.lower():
        return "failed", "blocked by Cloudflare (bot challenge); HIMS must allow this server"
    if 200 <= status < 300:
        try:
            body = json.loads(text)
        except ValueError:
            body = None
        if isinstance(body, dict) and str(body.get("status", "")).lower() == "failed":
            return "failed", f"HIMS rejected the note: {body.get('Message') or body.get('message') or snippet}"
        return "delivered", snippet
    if status in (408, 429) or status >= 500:
        return "retry", f"HIMS HTTP {status}: {snippet}"
    if status in (401, 403):
        return "failed", f"HIMS refused the token (HTTP {status}): {snippet}"
    return "failed", f"HIMS HTTP {status}: {snippet}"


# ---- delivery state ----------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class HimsDelivery:
    def __init__(self, runs_dir: Path, jobs: JobService, *, url: str, token: str,
                 backoff_s: tuple[float, ...], poll_s: float):
        self.root = Path(runs_dir) / "hims"
        self.root.mkdir(parents=True, exist_ok=True)
        self._jobs, self._url, self._token = jobs, url, token
        self._backoff, self._poll = backoff_s, poll_s
        self._lock = threading.RLock()       # record files
        self._tick_lock = threading.Lock()   # one delivery pass at a time
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- worker ----

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="hims-delivery", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(self._poll):
            try:
                self.tick()
            except Exception:  # a bad record must not end the worker
                log.exception("HIMS delivery pass failed")

    # ---- records ----

    def _path(self, audio_id: str) -> Path:
        return self.root / f"{audio_id}.json"

    def get(self, audio_id: str) -> dict[str, Any] | None:
        if not _AUDIO_ID.match(audio_id):
            return None
        with self._lock:
            path = self._path(audio_id)
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def _save(self, rec: dict[str, Any]) -> None:
        path = self._path(rec["audio_id"])
        tmp = path.with_suffix(".tmp")
        with self._lock:
            tmp.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)

    def _all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [json.loads(p.read_text(encoding="utf-8")) for p in self.root.glob("*.json")]

    def enqueue(self, audio_id: str, company_id: int, job_id: str) -> dict[str, Any]:
        """Start (or restart, after a failure) the delivery for an audio_id."""
        rec = {"audio_id": audio_id, "company_id": company_id, "job_id": job_id,
               "state": "pending", "attempts": 0, "next_attempt_at": 0.0,
               "last_http_status": None, "last_error": None, "hims_reply": None,
               "response": None, "needs_review": [], "created_at": _now_iso(),
               "delivered_at": None}
        self._save(rec)
        return rec

    def redeliver(self, audio_id: str) -> dict[str, Any] | None:
        """Push a failed delivery again, for example after the token was fixed."""
        with self._lock:
            rec = self.get(audio_id)
            if rec is None:
                return None
            if rec["state"] != "failed":
                raise ValueError(f"delivery is {rec['state']}, not failed")
            rec.update(state="pending", attempts=0, next_attempt_at=0.0, last_error=None)
            self._save(rec)
            return rec

    @staticmethod
    def view(rec: Mapping[str, Any]) -> dict[str, Any]:
        """The delivery block the status route shows."""
        retrying = rec["state"] == "pending" and rec["attempts"] > 0
        return {"state": rec["state"], "attempts": rec["attempts"],
                "last_http_status": rec["last_http_status"], "last_error": rec["last_error"],
                "hims_reply": rec["hims_reply"], "delivered_at": rec["delivered_at"],
                "next_attempt_at": datetime.fromtimestamp(rec["next_attempt_at"], UTC)
                .isoformat(timespec="seconds") if retrying else None}

    # ---- one pass ----

    def tick(self, now: float | None = None) -> None:
        with self._tick_lock:
            now = time.time() if now is None else now
            for rec in self._all():
                if rec["state"] == "pending":
                    self._process(rec, now)

    def _process(self, rec: dict[str, Any], now: float) -> None:
        job = self._jobs.get(rec["job_id"], include_private=True)
        if job is None or job["status"] == "failed":
            rec.update(state="job_failed",
                       last_error=(job or {}).get("error") or "the job record is missing")
            return self._save(rec)
        if job["status"] != "succeeded" or rec["next_attempt_at"] > now:
            return
        if not (self._url and self._token):
            rec["last_error"] = ("MEDIBYTES_HIMS_URL / MEDIBYTES_HIMS_TOKEN are not set; "
                                 "the note is held until they are")
            return self._save(rec)
        try:
            path = self._jobs.file_path(rec["job_id"], "discharge.json", include_private=True)
            note = json.loads(path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
            rec["response"] = format_response(note)
            rec["needs_review"] = needs_review(note)
        except (ValueError, OSError, AttributeError) as exc:
            rec.update(state="failed", last_error=f"cannot build the note: {exc}"[:500])
            return self._save(rec)

        kind, message, status = self._send(rec)
        rec["attempts"] += 1
        rec["last_http_status"] = status
        if kind == "delivered":
            rec.update(state="delivered", last_error=None, hims_reply=message,
                       delivered_at=_now_iso())
        elif kind == "retry" and rec["attempts"] <= len(self._backoff):
            rec.update(last_error=message, next_attempt_at=now + self._backoff[rec["attempts"] - 1])
        else:
            if kind == "retry":
                message = f"gave up after {rec['attempts']} attempts; last: {message}"
            rec.update(state="failed", last_error=message[:500])
        self._save(rec)

    def _send(self, rec: Mapping[str, Any]) -> tuple[str, str, int | None]:
        payload = {"audio_id": rec["audio_id"], "company_id": rec["company_id"],
                   "response": rec["response"]}
        req = urllib.request.Request(
            self._url, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json",
                     "Accept": "application/json", "User-Agent": "medibytes-hims/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=SEND_TIMEOUT_S) as resp:
                status, headers, body = resp.status, resp.headers, resp.read(_BODY_LIMIT)
        except urllib.error.HTTPError as exc:
            status, headers, body = exc.code, exc.headers, exc.read(_BODY_LIMIT)
        except (urllib.error.URLError, OSError) as exc:  # includes timeouts
            return "retry", f"cannot reach HIMS: {type(exc).__name__}", None
        kind, message = classify(status, headers, body.decode("utf-8", errors="replace"))
        return kind, message, status
