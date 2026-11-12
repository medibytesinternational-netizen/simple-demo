"""The rebuilt pipeline reproduces C1 exactly on all 40 Phone40 recordings.

Real preprocessing of the real mp4s; MedASR/small-int8 transcripts and gpt-4.1
replies replayed from the frozen baseline (evaluation/phone40/baseline). Every
chart row, verification fact and discharge-note item must equal what the
original code produced. Then the run is scored: it must be C1's 212/229.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.phone40.replay import AUDIO, BASELINE, clips, replay_pipeline
from evaluation.phone40.scoring import _slice, score_runs
from medibytes.domain import StageState
from medibytes.llm.replay import ReplayLLMClient
from medibytes.output import write_result

GOLDEN = BASELINE / "golden"
# Timings and run identifiers differ by construction; nothing else may.
VOLATILE = {"job_id", "term_validator_seconds", "llm_seconds"}


def _clean(obj):
    """JSON round-trip (tuples -> lists) and drop the volatile keys."""
    obj = json.loads(json.dumps(obj))

    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items() if k not in VOLATILE}
        if isinstance(o, list):
            return [walk(x) for x in o]
        return o
    return walk(obj)


def _golden(clip: str, name: str) -> dict:
    return json.loads((GOLDEN / clip / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    out = tmp_path_factory.mktemp("phone40")
    llm = ReplayLLMClient(*sorted(BASELINE.glob("trace*.jsonl")))
    pipeline = replay_pipeline(llm)
    results = {}
    for src in clips():
        result = pipeline.run(src, out / src.stem, job_id=src.stem)
        write_result(result, out / src.stem, src.name)
        results[src.stem] = result
    return out, results, llm


def test_all_forty_clips_ran_every_stage(replayed):
    _, results, llm = replayed
    assert len(results) == 40 == len(list(AUDIO.glob("*.mp4")))
    for clip, result in results.items():
        bad = [e for e in result.stages if e.state is not StageState.DONE]
        assert not bad, (clip, [(e.stage.value, e.state.value, e.detail) for e in bad])
    assert llm.misses == [], "a prompt drifted from the recorded C1 prompt"


@pytest.mark.parametrize("clip", [p.stem for p in clips()])
def test_clip_matches_the_original_code_field_for_field(replayed, clip):
    _, results, _ = replayed
    r = results[clip]
    old_t = _golden(clip, "transcript.json")
    new_t = {k: v for k, v in r.transcript.items() if k != "second_pass"}
    old_t["stt_provenance"].pop("job_id", None)
    assert _clean(new_t) == _clean(old_t)

    old_e = {k: v for k, v in _golden(clip, "entities.json").items()
             if k not in ("verify", "discharge")}
    new_e = {k: v for k, v in r.entities.items() if k not in ("verify", "discharge")}
    assert _clean(new_e) == _clean(old_e)
    assert _clean(r.verify) == _clean(_golden(clip, "verify.json"))
    assert _clean(r.discharge) == _clean(_golden(clip, "discharge.json"))


def test_the_replayed_run_scores_c1s_212_of_229(replayed):
    out, _, _ = replayed
    rep = score_runs(Path(out))
    total = _slice(rep, sorted(rep["clips"]))
    assert rep["missing"] == []
    assert (total["hit"], total["total"]) == (212, 229)
