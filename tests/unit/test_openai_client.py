"""The gpt-4.1 client against a local stand-in for the OpenAI API."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from medibytes.errors import LLMCallFailed, LLMTimeout, LLMUnavailable
from medibytes.llm.openai_client import OpenAIClient
from medibytes.llm.replay import ReplayLLMClient


class _Server:
    """Serves one canned response per test; records what it was sent."""

    def __init__(self, status=200, body=None, delay=0.0):
        outer = self
        self.requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 (http.server API)
                length = int(self.headers.get("Content-Length", 0))
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                       "json": json.loads(self.rfile.read(length))})
                time.sleep(delay)
                payload = json.dumps(body if body is not None else {
                    "choices": [{"message": {"content": '{"ok": true}'}}]}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def server():
    made = []

    def make(**kw):
        made.append(_Server(**kw))
        return made[-1]
    yield make
    for s in made:
        s.close()


def test_request_is_json_mode_temperature_zero_with_bearer_key(server):
    srv = server()
    client = OpenAIClient("sk-test", base_url=srv.url)
    assert client.complete_json("hello", timeout=5, max_tokens=99, stage="t") == '{"ok": true}'
    sent = srv.requests[0]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["auth"] == "Bearer sk-test"
    assert sent["json"]["model"] == "gpt-4.1"
    assert sent["json"]["temperature"] == 0
    assert sent["json"]["max_tokens"] == 99
    assert sent["json"]["response_format"] == {"type": "json_object"}
    assert sent["json"]["messages"] == [{"role": "user", "content": "hello"}]


def test_missing_key_is_unavailable_and_makes_no_call(server):
    srv = server()
    client = OpenAIClient("", base_url=srv.url)
    assert client.available() == (False, "OPENAI_API_KEY is not set")
    with pytest.raises(LLMUnavailable):
        client.complete_json("x", timeout=5, max_tokens=10, stage="t")
    assert srv.requests == []


@pytest.mark.parametrize("status, error", [(401, LLMUnavailable), (403, LLMUnavailable),
                                           (500, LLMCallFailed), (429, LLMCallFailed)])
def test_http_errors_are_typed(server, status, error):
    srv = server(status=status, body={"error": "x"})
    with pytest.raises(error):
        OpenAIClient("k", base_url=srv.url).complete_json("x", timeout=5, max_tokens=10, stage="t")


def test_a_reply_without_a_message_is_a_failed_call(server):
    srv = server(body={"choices": []})
    with pytest.raises(LLMCallFailed, match="no message"):
        OpenAIClient("k", base_url=srv.url).complete_json("x", timeout=5, max_tokens=10, stage="t")


def test_slow_server_is_a_timeout(server):
    srv = server(delay=1.5)
    with pytest.raises(LLMTimeout):
        OpenAIClient("k", base_url=srv.url).complete_json("x", timeout=0.3, max_tokens=10, stage="t")


def test_unreachable_server_is_unavailable():
    import socket
    with socket.socket() as s:  # a port nothing listens on once the socket closes
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    client = OpenAIClient("k", base_url=f"http://127.0.0.1:{port}/v1")
    with pytest.raises(LLMUnavailable):
        client.complete_json("x", timeout=15, max_tokens=10, stage="t")


def test_trace_records_every_call_and_replays(server, tmp_path):
    srv = server()
    trace = tmp_path / "trace.jsonl"
    client = OpenAIClient("k", base_url=srv.url, trace=trace)
    client.complete_json("prompt one", timeout=5, max_tokens=10, stage="term_validate")
    rec = json.loads(trace.read_text(encoding="utf-8").splitlines()[0])
    assert rec["stage"] == "term_validate" and rec["prompt"] == "prompt one"
    assert rec["raw_output"] == '{"ok": true}' and rec["error"] is None

    replay = ReplayLLMClient(trace)
    assert replay.complete_json("prompt one", timeout=1, max_tokens=1, stage="x") == '{"ok": true}'
    with pytest.raises(LookupError):
        replay.complete_json("never recorded", timeout=1, max_tokens=1, stage="x")
    assert replay.misses == ["never recorded"]
