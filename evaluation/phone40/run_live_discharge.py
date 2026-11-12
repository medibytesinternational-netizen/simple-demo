"""Re-run the Phone40 discharge note with live gpt-4.1, everything else replayed.

Transcripts come from `baseline/asr_cache`, and the chart stages' gpt-4.1
replies (term validation, context repair) from the baseline trace - those
prompts did not change. Only the note stages (`discharge*`) call gpt-4.1, and
each call is appended to `--trace`; a later run with the same trace replays
them for free and only calls for prompts it has not seen.

    python -m evaluation.phone40.run_live_discharge --out runs/sections_live
    python -m evaluation.phone40.section_coverage runs/sections_live --compare evaluation/phone40/baseline/golden
"""
from __future__ import annotations

import argparse
from pathlib import Path

from medibytes.config import Settings
from medibytes.errors import ReplayMiss
from medibytes.llm.openai_client import OpenAIClient
from medibytes.llm.replay import ReplayLLMClient
from medibytes.output import write_result

from .replay import BASELINE, clips, replay_pipeline


class NoteLiveClient:
    """Recorded replies for the chart stages; recorded-or-live for the note stages."""

    def __init__(self, live: OpenAIClient, trace: Path):
        self.model = live.model
        self._chart = ReplayLLMClient(*sorted(BASELINE.glob("trace*.jsonl")))
        self._seen = ReplayLLMClient(trace) if trace.is_file() else None
        self._live = live
        self.live_calls = 0

    def available(self) -> tuple[bool, str]:
        return self._live.available()

    def complete_json(self, prompt: str, *, timeout: float, max_tokens: int, stage: str) -> str:
        if not stage.startswith("discharge"):
            return self._chart.complete_json(prompt, timeout=timeout, max_tokens=max_tokens,
                                             stage=stage)
        if self._seen is not None:
            try:
                return self._seen.complete_json(prompt, timeout=timeout, max_tokens=max_tokens,
                                                stage=stage)
            except ReplayMiss:
                pass
        self.live_calls += 1
        return self._live.complete_json(prompt, timeout=timeout, max_tokens=max_tokens,
                                        stage=stage)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.phone40.run_live_discharge",
                                 description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trace", help="note-stage trace to replay and extend "
                                    "(default: <out>/discharge_trace.jsonl)")
    ap.add_argument("--clips", nargs="*", help="only these clips, e.g. s12 s30")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    trace = Path(a.trace) if a.trace else out / "discharge_trace.jsonl"
    llm = NoteLiveClient(OpenAIClient(Settings.from_env().openai_api_key, trace=trace), trace)
    pipeline = replay_pipeline(llm)
    for src in clips():
        if a.clips and src.stem not in a.clips:
            continue
        result = pipeline.run(src, out / src.stem, job_id=src.stem)
        write_result(result, out / src.stem, src.name)
        flags = [f"{e.stage.value}:{e.state.value}({e.detail})" for e in result.stages
                 if e.state.value != "done"]
        print(src.stem, " ".join(flags) or "ok", flush=True)
    print(f"{llm.live_calls} live gpt-4.1 calls; trace: {trace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
