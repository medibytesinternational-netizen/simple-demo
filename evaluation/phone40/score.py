"""Score a pipeline run against the Phone40 gold.

    python -m medibytes evaluation/phone40/audio --out runs/c1_check
    python -m evaluation.phone40.score runs/c1_check
    python -m evaluation.phone40.score runs/new --compare runs/c1_check   # paired, per fact

C1 as measured: dev 107/119 (89.9%), held-out 105/110 (95.5%), all 212/229 (92.6%).
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .scoring import _line, _slice, compare, misses, score_runs, summarise

C1_FACTS = (212, 229)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.phone40.score", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs_dir", help="the --out folder of a `python -m medibytes` run")
    ap.add_argument("--compare", help="a second runs folder to pair against (this one is 'a')")
    ap.add_argument("--misses", action="store_true", help="list every miss and spurious span")
    ap.add_argument("--json", help="also write the summary here")
    a = ap.parse_args(argv)

    rep = score_runs(Path(a.runs_dir))
    summary = summarise(rep)
    both = _slice(rep, sorted(rep["clips"]))
    print(a.runs_dir)
    print(_line("dev", summary["in_sample"]))
    print(_line("held-out", summary["held_out"]))
    print(_line("all 40", both))
    hit, total = both["hit"], both["total"]
    print(f"\nC1 as measured: {C1_FACTS[0]}/{C1_FACTS[1]}; this run: {hit}/{total} "
          f"({'same' if (hit, total) == C1_FACTS else f'{hit - C1_FACTS[0]:+d} facts'})")
    if rep["missing"]:
        print(f"  NOT SCORED (no entities.json): {len(rep['missing'])} clips, e.g. {rep['missing'][:3]}")
    if a.misses:
        print("\n".join(["", *misses(rep)]))
    out: dict[str, Any] = {"summary": summary, "all": both}
    if a.compare:
        cmp_ = compare(rep, score_runs(Path(a.compare)))
        print(f"\npaired vs {a.compare}: {cmp_['facts_compared']} facts; this run only "
              f"{len(cmp_['a_only'])}, other only {len(cmp_['b_only'])}, "
              f"net {cmp_['net_a_minus_b']:+d}, exact McNemar p={cmp_['p_exact_mcnemar']}")
        out["compare"] = {**cmp_, "a_only": [list(k) for k in cmp_["a_only"]],
                          "b_only": [list(k) for k in cmp_["b_only"]]}
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=2, default=list), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
