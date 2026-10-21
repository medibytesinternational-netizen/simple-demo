"""Pull one patient's results from a hospital FHIR server and ingest them.

    python -m app.integrations.pull --base-url https://hms.example/fhir --mrn MB-1001

Searches Patient by identifier, then Observation and MedicationRequest for that patient, follows
``next`` page links, and feeds the same ingest function the POST route uses.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlsplit

from sqlalchemy.orm import Session

from .ingest import ingest_bundle
from .outbox import _NoRedirect

MAX_PAGES = 50
TIMEOUT_SECONDS = 20

Fetch = Callable[[str], dict[str, Any]]


class PullError(RuntimeError):
    pass


def _origin(url: str) -> tuple[str, int | None]:
    parts = urlsplit(url)
    return (parts.hostname or "").lower(), parts.port


def http_get_json(url: str) -> dict[str, Any]:
    headers = {"Accept": "application/fhir+json"}
    token = os.environ.get("FHIR_AUTH_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    handlers: list[Any] = [_NoRedirect()]
    if (urlsplit(url).hostname or "") in {"127.0.0.1", "localhost", "::1"}:
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise PullError(f"hospital system answered HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise PullError(f"could not read the hospital system: {type(exc).__name__}") from exc


def _search(base: str, path: str, fetch: Fetch) -> list[dict[str, Any]]:
    """Every resource from a search, following next-page links on the same server."""
    resources: list[dict[str, Any]] = []
    url: str | None = f"{base}/{path}"
    for _ in range(MAX_PAGES):
        if not url:
            break
        page = fetch(url)
        for entry in page.get("entry") or []:
            if isinstance(entry.get("resource"), dict):
                resources.append(entry["resource"])
        url = next((l.get("url") for l in page.get("link") or [] if l.get("relation") == "next"), None)
        if url and _origin(url) != _origin(base):
            raise PullError("a next-page link pointed at a different server; stopped")
    return resources


def _failed(db: Session, system: str, reason: str, resource: str) -> dict[str, Any]:
    """Record a pull that brought nothing in, so the status banner can say so."""
    empty: dict[str, Any] = {"resourceType": "Bundle", "type": "collection", "entry": []}
    return ingest_bundle(db, system, empty, None, kind="pull",
                         extra_errors=[{"resource": resource, "reason": reason}])


def pull(db: Session, base: str, mrn: str, system: str | None = None, fetch: Fetch | None = None) -> dict[str, Any]:
    base = base.rstrip("/")
    fetch = fetch or http_get_json
    system = system or urlsplit(base).hostname or "hospital"
    search = f"Patient?identifier={quote(mrn)}"
    try:
        patients = [r for r in _search(base, search, fetch) if r.get("resourceType") == "Patient"]
        if not patients:
            return _failed(db, system, "the hospital system has no patient with that number", search)
        patient = patients[0]
        # The search key is the MRN we were asked for; make sure the bundled Patient carries it.
        if not any(i.get("value") == mrn for i in patient.get("identifier") or []):
            patient = {**patient, "identifier": [*(patient.get("identifier") or []), {"value": mrn}]}
        entries = [{"resource": patient}]
        pid = quote(str(patient.get("id", "")))
        for kind in ("Observation", "MedicationRequest"):
            for resource in _search(base, f"{kind}?patient={pid}", fetch):
                entries.append({"resource": resource})
    except PullError as exc:
        return _failed(db, system, str(exc), search)
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": entries}
    return ingest_bundle(db, system, bundle, None, kind="pull")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull one patient's FHIR results and ingest them.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--mrn", required=True)
    parser.add_argument("--system", default=None, help="name recorded as the source (default: server host)")
    args = parser.parse_args(argv)

    from ..db import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        try:
            result = pull(db, args.base_url, args.mrn, args.system)
            db.commit()
        except PullError as exc:
            db.rollback()
            print(json.dumps({"created": 0, "skipped": 0, "errors": 1, "details": [str(exc)]}))
            return 1
    finally:
        db.close()
    print(json.dumps({k: result[k] for k in ("created", "skipped", "errors")}))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
