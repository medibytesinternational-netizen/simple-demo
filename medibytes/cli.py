"""Command line: run the pipeline over audio files or folders.

    python -m medibytes clip.mp4 more_clips/ --out runs/try1

Writes <out>/<clip>/{cleaned.wav, transcript.json, entities.json, verify.json,
discharge.json, clean_meta.json, report.md} and <out>/review.csv.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from .config import Settings
from .errors import PipelineError
from .factory import build_pipeline
from .output import review_rows, write_result

AUDIO_EXT = {".wav", ".mp3", ".m4a", ".mp4", ".aac", ".flac", ".ogg", ".webm"}


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "clip"


def collect(inputs: list[str]) -> list[Path]:
    clips = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            clips += sorted(f for f in p.rglob("*") if f.suffix.lower() in AUDIO_EXT)
        elif p.is_file():
            clips.append(p)
        else:
            raise SystemExit(f"not found: {p}")
    return clips


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m medibytes", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="audio files and/or folders of audio")
    ap.add_argument("--out", default="runs/cli", help="output folder (default runs/cli)")
    a = ap.parse_args(argv)

    clips = collect(a.inputs)
    if not clips:
        raise SystemExit("no audio files found")
    try:
        pipeline = build_pipeline(Settings.from_env())
    except PipelineError as err:
        raise SystemExit(f"cannot start: {err}") from None

    out, review, failed = Path(a.out), [], 0
    for src in clips:
        print(f"-> {src}", flush=True)
        clip_dir = out / _slug(src.stem)
        try:
            result = pipeline.run(src, clip_dir, job_id=_slug(src.stem))
        except Exception as err:  # one bad clip must not end the batch
            failed += 1
            print(f"   FAILED: {type(err).__name__}: {err}", file=sys.stderr, flush=True)
            continue
        write_result(result, clip_dir, src.name)
        for stage in result.stages:
            if stage.state.value != "done":
                print(f"   {stage.stage.value}: {stage.state.value} - {stage.detail}", flush=True)
        review += [(src.name, *row) for row in review_rows(result.entities)]

    out.mkdir(parents=True, exist_ok=True)
    with open(out / "review.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["clip", "kind", "item", "confidence", "colour", "detail",
                    "correct (y/n)", "notes"])
        w.writerows([*row, "", ""] for row in review)
    print(f"\n{len(clips) - failed}/{len(clips)} clips -> {out}")
    return 1 if failed else 0
