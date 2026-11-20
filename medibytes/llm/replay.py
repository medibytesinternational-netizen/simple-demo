"""Replay recorded gpt-4.1 replies from a trace .jsonl (tests and re-scoring only).

Keyed by the exact prompt text: a prompt the trace never recorded raises
`ReplayMiss`, so any drift in a prompt builder fails loudly instead of quietly
calling a model. A prompt recorded more than once replays its replies in order
(the discharge author retries the same prompt on unusable JSON).
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path

from ..config import C1
from ..errors import LLMCallFailed, ReplayMiss


class ReplayLLMClient:
    def __init__(self, *traces: Path, model: str = C1.llm.model):
        self.model = model
        self._replies: dict[str, deque] = defaultdict(deque)
        for trace in traces:
            for line in Path(trace).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._replies[rec["prompt"]].append(rec)
        self.calls = 0
        # The LLM stages catch every exception to keep a row as the matcher made
        # it, so a miss is also recorded here for the test to assert on.
        self.misses: list[str] = []

    def available(self) -> tuple[bool, str]:
        return True, ""

    def complete_json(self, prompt: str, *, timeout: float, max_tokens: int, stage: str) -> str:
        queue = self._replies.get(prompt)
        if not queue:
            self.misses.append(prompt)
            raise ReplayMiss(f"no recorded reply for a {stage} prompt: {prompt[:120]!r}")
        rec = queue.popleft() if len(queue) > 1 else queue[0]
        self.calls += 1
        if rec.get("error"):
            raise LLMCallFailed(rec["error"])
        return rec.get("raw_output") or ""
