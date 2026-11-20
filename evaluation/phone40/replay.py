"""Re-run the pipeline on Phone40 without decoding audio or (optionally) calling gpt-4.1.

`CachedRecognizer` serves the MedASR and small-int8 transcripts recorded in
`baseline/asr_cache`, keyed by the SHA-256 of the cleaned WAV (preprocessing is
deterministic, so the same mp4 always yields the same key). Combined with the
recorded gpt-4.1 trace this replays C1 exactly; combined with the live client it
re-scores an extractor change in minutes:

    python -m evaluation.phone40.replay --out runs/replay            # recorded gpt-4.1
    python -m evaluation.phone40.replay --out runs/rescore --live    # live gpt-4.1
    python -m evaluation.phone40.score runs/replay
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from medibytes.config import Settings
from medibytes.errors import SpeechModelUnavailable
from medibytes.llm.openai_client import OpenAIClient
from medibytes.llm.replay import ReplayLLMClient
from medibytes.output import write_result
from medibytes.pipeline import Pipeline
from medibytes.preprocessing.preprocessor import Preprocessor

HERE = Path(__file__).resolve().parent
BASELINE = HERE / "baseline"
AUDIO = HERE / "audio"


class CachedRecognizer:
    """A `ports.SpeechRecognizer` that returns a recorded transcript for a WAV."""

    def __init__(self, cache_dir: Path, model_key: str, label: str, cache_keys: dict[str, str]):
        self.cache_dir = Path(cache_dir)
        self.model_key = model_key  # "medasr" or "small-int8", as the cache files are named
        self.label = label
        self.cache_keys = cache_keys

    def transcribe(self, wav: Path) -> dict:
        wav = Path(wav)
        digest = hashlib.sha256(wav.read_bytes()).hexdigest()[:24]
        path = self.cache_dir / f"{digest}-{self.model_key}-greedy.json"
        if not path.is_file():
            # The frozen cache was recorded on Windows. Different bundled ffmpeg
            # builds can produce different WAV bytes for the same MP4 on macOS or
            # Linux, even when the recognized transcript is identical. Keep the
            # original content-hash lookup first, then use the clip's golden
            # transcript to locate the unchanged recorded cache entry.
            baseline_key = self.cache_keys.get(wav.parent.name)
            if baseline_key:
                path = self.cache_dir / f"{baseline_key}-{self.model_key}-greedy.json"
        if not path.is_file():
            raise SpeechModelUnavailable(f"no cached {self.model_key} transcript for {wav}")
        return json.loads(path.read_text(encoding="utf-8"))


def _cache_keys_by_clip(baseline: Path) -> dict[str, str]:
    """Map Phone40 clip ids to frozen ASR cache keys by their MedASR transcript."""
    golden = {}
    for path in (baseline / "golden").glob("*/transcript.json"):
        transcript = json.loads(path.read_text(encoding="utf-8"))
        golden[transcript.get("text", "").strip()] = path.parent.name

    keys = {}
    for path in (baseline / "asr_cache").glob("*-medasr-greedy.json"):
        transcript = json.loads(path.read_text(encoding="utf-8"))
        clip = golden.get(transcript.get("text", "").strip())
        if clip:
            keys[clip] = path.name.removesuffix("-medasr-greedy.json")
    return keys


def replay_pipeline(llm=None, baseline: Path = BASELINE) -> Pipeline:
    """C1 with recorded transcripts; recorded gpt-4.1 unless `llm` is given."""
    cache = baseline / "asr_cache"
    cache_keys = _cache_keys_by_clip(baseline)
    traces = sorted(baseline.glob("trace*.jsonl"))
    return Pipeline(preprocessor=Preprocessor(),
                    first_pass=CachedRecognizer(cache, "medasr", "medasr", cache_keys),
                    second_pass=CachedRecognizer(cache, "small-int8", "small-int8", cache_keys),
                    llm=llm or ReplayLLMClient(*traces))


def clips() -> list[Path]:
    return sorted(AUDIO.glob("s*.mp4"), key=lambda p: int(p.stem[1:]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.phone40.replay", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--live", action="store_true", help="call gpt-4.1 instead of the trace")
    a = ap.parse_args(argv)
    llm = None
    if a.live:
        s = Settings.from_env()
        llm = OpenAIClient(s.openai_api_key, trace=s.llm_trace)
    pipeline = replay_pipeline(llm)
    for src in clips():
        out = Path(a.out) / src.stem
        result = pipeline.run(src, out, job_id=src.stem)
        write_result(result, out, src.name)
        flags = [f"{e.stage.value}:{e.state.value}" for e in result.stages
                 if e.state.value != "done"]
        print(src.stem, " ".join(flags) or "ok", flush=True)
    if isinstance(pipeline.llm, ReplayLLMClient) and pipeline.llm.misses:
        print(f"WARNING: {len(pipeline.llm.misses)} prompts were not in the trace")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
