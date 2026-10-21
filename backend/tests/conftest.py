"""Test harness: a temporary database, cached mode, and one app instance per session.

The environment is set before the app is imported because app.config reads it once.
"""

from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="medibytes-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["LLM_MODE"] = "cached"
os.environ["OPENAI_API_KEY"] = ""
os.environ.pop("OPENAI_BASE_URL", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def _client():
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def client(_client):
    """Client reset to the full rehearsal data before every test."""
    assert _client.post("/api/demo/reset?mode=rehearsal").status_code == 200
    return _client


@pytest.fixture()
def fresh(_client):
    """Client reset to the empty record (demographics and allergy only)."""
    assert _client.post("/api/demo/reset?mode=start").status_code == 200
    return _client
