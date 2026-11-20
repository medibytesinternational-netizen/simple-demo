"""gpt-4.1 over the OpenAI Chat Completions API (stdlib HTTP, no SDK).

Every call asks for a JSON object at temperature 0. The API key is read once
from `Settings` and sent only to api.openai.com. With `trace` set, every call
appends {stage, model, prompt, raw_output, error, seconds} to a .jsonl file, the
record the Phone40 evaluation was audited from and `ReplayLLMClient` replays.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import C1
from ..errors import LLMCallFailed, LLMTimeout, LLMUnavailable


class OpenAIClient:
    """The one `ports.LLMClient` the pipeline ships with."""

    def __init__(self, api_key: str, *, model: str = C1.llm.model,
                 base_url: str = C1.llm.base_url, trace: Path | None = None):
        self.model = model
        self._key = api_key.strip()
        self._base = base_url.rstrip("/")
        self._trace = Path(trace) if trace else None

    def available(self) -> tuple[bool, str]:
        if not self._key:
            return False, "OPENAI_API_KEY is not set"
        return True, ""

    def complete_json(self, prompt: str, *, timeout: float, max_tokens: int, stage: str) -> str:
        t0, text, error = time.perf_counter(), None, None
        try:
            if not self._key:
                raise LLMUnavailable("OPENAI_API_KEY is not set")
            reply = self._post("/chat/completions", {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0,
                "max_tokens": max_tokens,
                "stream": False,
            }, timeout)
            try:
                text = reply["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError):
                raise LLMCallFailed("LLM reply had no message") from None
            return text
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:200]
            raise
        finally:
            self._write_trace({"stage": stage, "model": self.model, "prompt": prompt,
                               "raw_output": text, "error": error,
                               "seconds": round(time.perf_counter() - t0, 3)})

    def _post(self, path: str, payload: dict, timeout: float) -> dict:
        req = urllib.request.Request(
            self._base + path, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise LLMUnavailable(f"OpenAI refused the API key (HTTP {e.code})") from None
            raise LLMCallFailed(f"OpenAI HTTP {e.code}") from None
        except TimeoutError:
            raise LLMTimeout(f"gpt-4.1 timed out after {timeout}s") from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, TimeoutError):
                raise LLMTimeout(f"gpt-4.1 timed out after {timeout}s") from None
            raise LLMUnavailable(f"cannot reach {self._base}") from None
        except OSError:
            raise LLMUnavailable(f"cannot reach {self._base}") from None
        except json.JSONDecodeError:
            raise LLMCallFailed("OpenAI returned non-JSON") from None

    def _write_trace(self, record: dict) -> None:
        if not self._trace:
            return
        try:
            self._trace.parent.mkdir(parents=True, exist_ok=True)
            with open(self._trace, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:  # a trace is an audit aid; it must never fail a call
            pass
