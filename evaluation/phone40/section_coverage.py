"""Did every dictated part reach its section of the discharge note? (Phone40, any run.)

Each Phone40 script labels its sections ("Examination: ...", "Plan: ...", "Diet:
...", "General: ..."), so the script says what each of the six sections should
hold. The script is split into those sections and each section into its parts
(at commas and semicolons). A part is *reached* when at least half of its
content words appear among the note items of that section. Number words are
normalised to digits and near-spellings count (MedASR noise), so the measure
is about content, not exact wording.

    python -m evaluation.phone40.section_coverage evaluation/phone40/baseline/golden
    python -m evaluation.phone40.section_coverage runs/sections_live --compare evaluation/phone40/baseline/golden
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path

from medibytes.extraction.numerals import numwords_to_digits
from medibytes.llm.discharge import DISCHARGE_SECTIONS

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE / "scripts"

_SENT = re.compile(r"(?<=\.)\s+(?=[A-Z])")
_LABELS = {"Examination": "examination_findings", "Investigations": "plan_of_management",
           "Plan": "plan_of_management", "Diet": "diet_instructions",
           "General": "general_instructions"}
_LABEL = re.compile(r"^(%s):\s*" % "|".join(_LABELS))
# Words that name a part, not its content: "Past history hypertension".
_LEAD = re.compile(r"^(?:no past major illness|past history(?: of)?|past diagnosis|"
                   r"provisional diagnosis|diagnosis|now)\b\s*", re.I)
_STOP = frozenset(
    "a an the and or of in on at to for with is was are be by as per if from".split()
    # units: the note writes "mg", "mmHg", "%" for spoken "milligrams" ...
    + "mg milligram milligrams mcg microgram micrograms g gram grams ml millilitre millilitres "
      "millimetres millimeters mercury mmhg percent beats minute bpm degrees degree fahrenheit "
      "celsius kilos kg kilograms litres litre l".split())


def script_sections(text: str) -> dict[str, list[str]]:
    """{section: [parts]} from one labelled script. Denials are left out."""
    out: dict[str, list[str]] = {k: [] for k in DISCHARGE_SECTIONS}
    for i, sent in enumerate(_SENT.split(text.strip())):
        sent = sent.strip().rstrip(".")
        m = _LABEL.match(sent)
        if i == 0:
            section = "present_illness"
        elif m:
            section, sent = _LABELS[m.group(1)], sent[m.end():]
        elif sent.startswith("Denies"):
            continue  # a denial asks for no positive item
        elif sent.startswith(("Past ", "No past")):
            section = "previous_diagnosis"
        else:
            section = "plan_of_management"  # "Follow up in two days", "Neurology in three days"
        for part in re.split(r"[;,]", sent):
            part = _LEAD.sub("", part.strip()).strip()
            if part:
                out[section].append(part)
    return out


def _words(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", numwords_to_digits(str(text or "").lower()))
    return [t for t in toks if t not in _STOP]


def _heard(word: str, pool: set[str]) -> bool:
    if word in pool:
        return True
    return len(word) >= 4 and any(
        len(p) >= 4 and difflib.SequenceMatcher(None, word, p).ratio() >= 0.8 for p in pool)


def part_reached(part: str, items: list[dict]) -> bool:
    want = _words(part)
    if not want:
        return True
    pool = {w for it in items for w in _words(it.get("text", ""))}
    return sum(_heard(w, pool) for w in want) / len(want) >= 0.5


def score_note(script: str, note: dict) -> dict:
    """Per-section {parts, reached, unreached} for one clip."""
    sections = note.get("sections", {})
    everything = [it for s in sections.values() for it in (s or {}).get("items", [])]
    out = {}
    for key, parts in script_sections(script).items():
        items = (sections.get(key) or {}).get("items", []) or []
        missed = [p for p in parts if not part_reached(p, items)]
        out[key] = {"parts": len(parts), "reached": len(parts) - len(missed),
                    "anywhere": sum(part_reached(p, everything) for p in parts),
                    "filled": bool(items), "unreached": missed}
    return out


def score_run(run_dir: Path) -> dict:
    """Score every clip folder (s1..s40) under `run_dir` that has a discharge.json."""
    clips = {}
    for script in sorted(SCRIPTS.glob("s*.txt"), key=lambda p: int(p.stem[1:])):
        note_path = Path(run_dir) / script.stem / "discharge.json"
        if note_path.is_file():
            note = json.loads(note_path.read_text(encoding="utf-8"))
            clips[script.stem] = score_note(script.read_text(encoding="utf-8"), note)
    totals = {}
    for key in DISCHARGE_SECTIONS:
        rows = [c[key] for c in clips.values()]
        totals[key] = {
            "parts": sum(r["parts"] for r in rows),
            "reached": sum(r["reached"] for r in rows),
            "anywhere": sum(r["anywhere"] for r in rows),
            "dictated": sum(r["parts"] > 0 for r in rows),
            "filled": sum(r["parts"] > 0 and r["filled"] for r in rows)}
    return {"run": str(run_dir), "clips": clips, "totals": totals}


def _pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "-"


def format_report(rep: dict, base: dict | None = None) -> str:
    t, lines = rep["totals"], [f"{len(rep['clips'])} clips: {rep['run']}"]
    head = f"{'section':22} {'sections filled':>18} {'parts in section':>18} {'parts anywhere':>18}"
    lines += [head + ("   before (parts in section)" if base else ""), "-" * len(head)]
    for key in DISCHARGE_SECTIONS:
        r = t[key]
        row = (f"{key:22} {_pct(r['filled'], r['dictated']):>18} "
               f"{_pct(r['reached'], r['parts']):>18} {_pct(r['anywhere'], r['parts']):>18}")
        if base:
            b = base["totals"][key]
            row += f"   {_pct(b['reached'], b['parts'])}"
        lines.append(row)
    p = sum(t[k]["parts"] for k in t)
    lines.append(f"{'ALL':22} {_pct(sum(t[k]['filled'] for k in t), sum(t[k]['dictated'] for k in t)):>18} "
                 f"{_pct(sum(t[k]['reached'] for k in t), p):>18} "
                 f"{_pct(sum(t[k]['anywhere'] for k in t), p):>18}"
                 + (f"   {_pct(sum(base['totals'][k]['reached'] for k in t), p)}" if base else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evaluation.phone40.section_coverage",
                                 description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", help="folder holding s1/discharge.json ... s40/discharge.json")
    ap.add_argument("--compare", help="another run folder to show as 'before'")
    ap.add_argument("--json", help="write the full per-clip report here")
    ap.add_argument("--misses", action="store_true", help="list every unreached part")
    a = ap.parse_args(argv)
    rep = score_run(Path(a.run_dir))
    base = score_run(Path(a.compare)) if a.compare else None
    print(format_report(rep, base))
    if a.misses:
        for clip, secs in rep["clips"].items():
            for key, r in secs.items():
                for part in r["unreached"]:
                    print(f"  {clip:4} {key:22} {part}")
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
