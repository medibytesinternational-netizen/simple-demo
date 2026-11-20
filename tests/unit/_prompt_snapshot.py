"""Builds every stage-7 prompt for Phone40 clip s1; used to pin the discharge template."""
import json
from pathlib import Path

from medibytes.llm import discharge as d

GOLDEN = Path(__file__).resolve().parents[2] / "evaluation" / "phone40" / "baseline" / "golden" / "s1"


def prompts(**kw):
    tr = json.loads((GOLDEN / "transcript.json").read_text(encoding="utf-8"))
    ver = json.loads((GOLDEN / "verify.json").read_text(encoding="utf-8"))
    text, norm, segs = tr["text"], tr.get("normalized_en", ""), tr.get("segments", [])
    parts = [{"quote": text[:40], "section": "plan_of_management"}]
    unused = {"plan_of_management": [text[:40]], "diet_instructions": [text[50:90]]}
    return {
        "discharge": d._discharge_prompt(text, norm, ver, segs, parts, **kw),
        "discharge_noparts": d._discharge_prompt(text, norm, ver, segs, None, **kw),
        "analyse": d._analyse_prompt(text, **kw),
        "coverage": d._coverage_prompt(unused, text, **kw),
        "verified_lines": d._verified_lines(ver, segs, **kw),
    }


def hardening(**kw):
    """gate -> canonicalize -> merge -> coverage over s1's golden note, as the pipeline chains them."""
    tr = json.loads((GOLDEN / "transcript.json").read_text(encoding="utf-8"))
    ver = json.loads((GOLDEN / "verify.json").read_text(encoding="utf-8"))
    note = json.loads((GOLDEN / "discharge.json").read_text(encoding="utf-8"))
    text, norm = tr["text"], tr.get("normalized_en", "")
    raw = {"sections": d._parse_sections(note["sections"], **kw), "provenance": {}}
    gated = d.gate_discharge(raw, text, norm, ver, **kw)
    locked = d.canonicalize_discharge(gated, ver, **kw)
    merged = d.merge_discharge(ver, locked, text, norm, **kw)
    covered = d.check_coverage(merged, text, None, **kw)
    return {"gated": gated, "locked": locked, "merged": merged, "covered": covered,
            "stamped": d.stamp_schema(covered, **kw)}
