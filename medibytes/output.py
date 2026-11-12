"""Write one clip's result to disk: the JSON files plus a human-readable report."""
from __future__ import annotations

import json
from pathlib import Path

from .domain import ClipResult

FILES = ("transcript.json", "entities.json", "verify.json", "discharge.json",
         "clean_meta.json", "report.md")


def write_result(result: ClipResult, out_dir: Path, source_name: str) -> list[str]:
    """Write every output file next to `cleaned.wav`; return the names written."""
    out_dir = Path(out_dir)
    for name, obj in (("transcript.json", result.transcript),
                      ("entities.json", result.entities),
                      ("verify.json", result.verify),
                      ("discharge.json", result.discharge),
                      ("clean_meta.json", result.clean_meta)):
        (out_dir / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False),
                                    encoding="utf-8")
    (out_dir / "report.md").write_text(render_report(result, source_name), encoding="utf-8")
    return list(FILES)


def _dose(d: dict) -> str:
    if d.get("dose") in (None, ""):
        return "no dose"
    return f"{d['dose']:g} {d.get('unit') or ''}".strip()


def _drug_provenance(d: dict) -> str:
    """What a reviewer needs to judge a repaired drug: heard -> chosen, and why."""
    bits = []
    if d.get("raw_token") and d["raw_token"].lower() != d["name"].lower():
        bits.append(f"heard `{d['raw_token']}`")
    ref = d.get("reference") or {}
    if ref:
        bits.append(f"reference {ref.get('kind')}: {ref.get('name')}")
    cands = d.get("candidates") or []
    if cands:
        bits.append("candidates " + ", ".join(
            f"{c['name']} {c['score']:.2f}" for c in cands[:4] if c.get("name")
            and isinstance(c.get("score"), int | float)))
    val = d.get("validation")
    if val:
        bits.append(f"gpt-4.1 {val.get('status')}")
    if d.get("second_pass"):
        bits.append(f"heard only by {d['second_pass']}")
    return "; ".join(bits)


def review_rows(entities: dict):
    """(kind, item, confidence, colour, detail) for everything worth checking."""
    for d in entities.get("drugs", []):
        item = f"{'NOT GIVEN: ' if d.get('negated') else ''}{d['name']} {_dose(d)}"
        yield ("drug", item, d.get("confidence"), d.get("color"),
               _drug_provenance(d) or d.get("note", ""))
    for v in entities.get("vitals", []):
        yield ("vital", v.get("text", ""), v.get("confidence"), v.get("color"), v.get("note", ""))
    for a in entities.get("allergies", []):
        yield ("allergy", f"{'DENIED ' if a.get('negated') else ''}{a.get('text', '')}",
               a.get("confidence"), a.get("color"), a.get("note", ""))
    for b in (entities.get("verify") or {}).get("brand_mentions", []) or []:
        yield ("brand", f"{b['brand']} {b['number']}", 0.70, "RED",
               f"brand mention - not charted; is {', '.join(b['substances'])}")
    prov = (entities.get("discharge") or {}).get("provenance", {}) or {}
    if prov.get("schema") == "INVALID":
        yield ("discharge", "schema INVALID", 0.70, "RED", prov.get("schema_error", ""))


def render_report(result: ClipResult, source_name: str) -> str:
    m, t, e = result.clean_meta, result.transcript, result.entities
    out = [f"# {source_name}", "", "## Stages", "",
           "| stage | state | seconds | detail |", "|---|---|---|---|"]
    out += [f"| {s.stage.value} | {s.state.value} | {s.seconds} | {s.detail.replace('|', '/')} |"
            for s in result.stages]
    out += ["", "## Audio", "",
            f"- {m.get('duration_s')} s, SNR {m.get('snr_db')} dB, speech ratio "
            f"{m.get('vad_ratio')}, RMS {m.get('rms_dbfs_before')} -> {m.get('rms_dbfs_after')} dBFS",
            "", "## Transcript", "", f"- engine `{t.get('stt_engine')}`", "",
            f"> {t.get('text', '')}", "", "**Normalised**", "", f"> {t.get('normalized_en', '')}",
            "", "## Chart rows", ""]
    rows = list(review_rows(e))
    if rows:
        out += ["| kind | item | colour | conf | detail |", "|---|---|---|---|---|"]
        out += [f"| {k} | {i} | {c or ''} | {conf if conf is not None else ''} | "
                f"{d.replace('|', '/')} |" for k, i, conf, c, d in rows]
    else:
        out.append("_nothing extracted_")
    v = e.get("verify") or {}
    if v.get("summary"):
        out += ["", "## Verification", "",
                f"- facts {v['summary'].get('total', 0)}: " + (", ".join(
                    f"{k} {n}" for k, n in sorted(v["summary"].items())
                    if k not in ("total", "numerals", "error")) or "-")]
    d = e.get("discharge") or {}
    out += ["", "## Discharge note", ""]
    for sec, block in (d.get("sections") or {}).items():
        items = (block or {}).get("items", []) or []
        out.append(f"### {sec.replace('_', ' ').capitalize()} ({len(items)})")
        for it in items:
            tag = f" [{it['verified_status']}]" if it.get("verified_status") else ""
            out.append(f"- {it.get('text', '')}{tag} - heard: \"{str(it.get('source_sentence', ''))[:120]}\"")
        if not items:
            out.append("_not dictated_")
    prov = d.get("provenance") or {}
    if prov:
        out += ["", f"- note: `{prov.get('llm_engine')}`, dropped unproven: "
                    f"{prov.get('dropped_unproven', 0)}, prefilled: {prov.get('prefilled', 0)}, "
                    f"schema: `{prov.get('schema', 'unchecked')}`"]
    return "\n".join(out) + "\n"
