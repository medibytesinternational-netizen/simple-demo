"""Fact-level scoring of pipeline output against the Phone40 gold.

Ported unchanged from the evaluation that measured C1 (clinical_eval.gold,
gold_v2, score and fact_score), so a re-score here is the same yardstick:
212/229 facts for C1. Every gold fact (vital, drug + polarity, dose, allergy) is
one boolean; intervals are Wilson and a clip-level cluster bootstrap; two runs
are compared per fact with an exact McNemar test.
"""
from __future__ import annotations

import json
import math
import random
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GOLD_PATH = Path(__file__).with_name("gold.json")
SPLIT_PATH = Path(__file__).with_name("split.json")


@dataclass(frozen=True)
class Vital:
    kind: str                      # bp | pulse | temp_f | spo2 | rr | glucose
    value: float | None = None
    systolic: float | None = None
    diastolic: float | None = None
    unit: str = ""
    note: str = ""


@dataclass(frozen=True)
class Drug:
    name: str                      # canonical, lowercase
    dose: float | None = None
    unit: str | None = None
    frequency: str = ""
    aliases: tuple[str, ...] = ()
    negated: bool = False


@dataclass(frozen=True)
class Allergy:
    substance: str
    negated: bool                  # True = record asserts NO such allergy
    note: str = ""


@dataclass(frozen=True)
class Clip:
    clip_id: str
    speaker_role: str              # the voice the dictation is in
    vitals: tuple[Vital, ...] = ()
    drugs: tuple[Drug, ...] = ()
    allergies: tuple[Allergy, ...] = ()
    symptoms: tuple[str, ...] = ()
    negated_findings: tuple[str, ...] = ()
    diagnosis: str = ""
    history: tuple[str, ...] = ()


# Legitimate alternative spellings of the same substance (INN/USAN/British), so a
# correct-but-differently-named row is not scored as a miss.
_ALIASES = {
    "paracetamol": ("acetaminophen",), "salbutamol": ("albuterol",),
    "adrenaline": ("epinephrine",), "levothyroxine": ("thyroxine",),
    "sodium valproate": ("valproate",), "ipratropium bromide": ("ipratropium",),
    "normal saline": ("saline",), "amoxicillin": ("amoxycillin", "co-amoxiclav"),
    "clavulanic acid": ("clavulanate", "co-amoxiclav"),
}


def _drug(rec: dict, name: str) -> Drug:
    return Drug(name, dose=rec.get("dose"), unit=rec.get("unit"),
                aliases=(name, *_ALIASES.get(name, ())), negated=bool(rec.get("negated")))


def load(path: str | Path | None = None, *, include_borderline: bool = False,
         current_only: bool = False) -> dict[str, Clip]:
    """`path` scores another set written in this file's format (default: gold_v2.json)."""
    data = json.loads(Path(path or GOLD_PATH).read_text(encoding="utf-8"))["clips"]
    clips: dict[str, Clip] = {}
    for cid, c in data.items():
        vitals = tuple(
            Vital(v["kind"], value=v.get("value"), systolic=v.get("systolic"),
                  diastolic=v.get("diastolic"), unit=v["unit"],
                  note="historic" if v.get("historic") else "")
            for v in c["vitals"] if not (current_only and v.get("historic")))
        drugs = tuple(
            _drug(d, n) for d in c["drugs"]
            if include_borderline or not d.get("borderline")
            for n in d.get("components") or [d["name"]])
        allergies = tuple(
            Allergy(a["substance"], bool(a.get("negated")))
            for a in c["allergies"] if include_borderline or not a.get("borderline"))
        clips[cid] = Clip(clip_id=cid, speaker_role="dictation",
                          vitals=vitals, drugs=drugs, allergies=allergies)
    return clips


def _number_present(text: str, value: float) -> bool:
    """Is this clinical number recoverable from the text, in any spoken form?

    A decoder may write 98.6 as "98.6" or as "98 point 6"; 150/95 may appear as
    "150 over 95", "150/95" or "one fifty over ninety five". The pipeline's own
    `numwords_to_digits` converts spelled-out integers but not "point", so the
    decimal forms are matched explicitly rather than counted as misses.
    """

    from medibytes.extraction.numerals import numwords_to_digits

    haystack = numwords_to_digits(text)
    if float(value).is_integer():
        integral = str(int(value))
        # `(?!\d)` alone lets a decimal satisfy an integer: a temperature span
        # reading "98.6 degrees Fahrenheit" scored a gold SpO2 of 98, and clip
        # 002 carries both facts, so the vitals total was inflated by a
        # collision between two unrelated readings. A digit after the point is
        # a different number, not this one.
        return re.search(rf"(?<!\d){re.escape(integral)}(?!\d)(?!\.\d)",
                         haystack) is not None
    whole, frac = f"{value:.10g}".split(".")
    patterns = (
        rf"(?<!\d){re.escape(whole)}\.{re.escape(frac)}(?!\d)",
        rf"(?<!\d){re.escape(whole)}\s*point\s*{re.escape(frac)}(?!\d)",
    )
    return any(re.search(p, haystack, re.I) for p in patterns)


def _name_present(text: str, drug: Drug) -> bool:
    lowered = text.lower()
    return any(alias.lower() in lowered for alias in (drug.aliases or (drug.name,)))


def _extracted_drug(entities: Mapping[str, Any], drug: Drug) -> dict[str, Any] | None:
    for item in entities.get("drugs", []) or []:
        name = str(item.get("name", "")).lower()
        if name == drug.name.lower() or any(a.lower() == name for a in drug.aliases):
            return dict(item)
    return None


# Which gold kind an emitted vital span is talking about. The extractor emits
# untyped spans, so without this the scorer compares numbers alone - and a span
# reading "respiratory rate 92" scored a gold *pulse* of 92 as a hit. Worse, a
# single span containing every number in the transcript scored four of clip
# 001's five vitals. Deliberately written here rather than imported from
# the pipeline: the scorer should not borrow the judgement of the code it grades.
_KIND_CUES: tuple[tuple[str, str], ...] = (
    ("bp", r"\bBP\b|blood\s*pressure|\d+\s*(?:by|/|over)\s*\d+"),
    ("spo2", r"spo2|sp02|o2\s*sat|oxygen\s*sat|saturation|%|percent"),
    ("temp_f", r"temp|fahrenheit|celsius|degree|°"),
    ("rr", r"respiratory\s*rate|resp\b|respiration|breathing\s*rate"),
    ("pulse", r"pulse|heart\s*rate|\bHR\b"),
    # The concentration units are a cue in their own right: the decoder writes
    # "54 milligrams per decilitre" with no word "glucose" anywhere in the span.
    ("glucose", r"glucose|sugar|BGL|RBS|CBG|mg\s*/\s*d[lL]|mmol"
                r"|milligrams?\s+per\s+decilit(?:re|er)"
                r"|millimoles?\s+per\s+lit(?:re|er)"),
)


def span_kind(text: str) -> str | None:
    """The gold vital kind this span reports, or None if it names none.

    Order matters: `respiratory rate` is tested before `pulse` because "rate"
    appears in both cues, and a BP pair is tested first because "130/80"
    carries no word cue at all.
    """
    for kind, pattern in _KIND_CUES:
        if re.search(pattern, text, re.I):
            return kind
    return None


def _vital_candidates(entities: Mapping[str, Any], vital: Vital) -> list[int]:
    """Indices of emitted spans that report this gold vital, value and kind."""
    out = []
    for i, item in enumerate(entities.get("vitals", []) or []):
        span = str(item.get("text", ""))
        if span_kind(span) != vital.kind:
            continue
        if vital.kind == "bp":
            assert vital.systolic is not None and vital.diastolic is not None
            ok = (_number_present(span, vital.systolic)
                  and _number_present(span, vital.diastolic))
        else:
            assert vital.value is not None
            ok = _number_present(span, vital.value)
        if ok:
            out.append(i)
    return out


def _vital_hit(entities: Mapping[str, Any], vital: Vital) -> bool:
    """Does any extracted vital span report this gold fact? (type and value)"""
    return bool(_vital_candidates(entities, vital))


def _allergy_polarity(entities: Mapping[str, Any], allergy: Allergy) -> str:
    """`correct` / `wrong_polarity` / `missing` for one gold allergy."""

    for item in entities.get("allergies", []) or []:
        if str(item.get("text", "")).lower() != allergy.substance.lower():
            continue
        return "correct" if bool(item.get("negated")) == allergy.negated else "wrong_polarity"
    return "missing"


def _assign_vitals(clip: Clip, entities: Mapping[str, Any]) -> tuple[list[int | None], set[int]]:
    """One emitted span per gold vital, and the span indices nothing claimed.

    Without consumption the scorer asks `any()` per gold fact, so one span can
    satisfy several gold vitals at once and a transcript-sized blob scores
    them all. Assignment is greedy over the scarcest gold fact first, which is
    exact whenever candidate sets nest and good enough for 5 facts a clip.
    """
    cands = {i: _vital_candidates(entities, v) for i, v in enumerate(clip.vitals)}
    taken: dict[int, int] = {}
    for gi in sorted(cands, key=lambda i: len(cands[i])):
        for si in cands[gi]:
            if si not in taken.values():
                taken[gi] = si
                break
    n = len(entities.get("vitals", []) or [])
    return ([taken.get(i) for i in range(len(clip.vitals))],
            {i for i in range(n) if i not in taken.values()})


def _spurious_drugs(clip: Clip, entities: Mapping[str, Any]) -> list[str]:
    """Emitted drug rows that correspond to no gold drug.

    This is the half of the picture the harness never had: every total it
    reports is `hit / gold_total`, so emitting the entire 33-name formulary
    scored full drug recall and nothing counted against it.
    """
    known = {d.name.lower() for d in clip.drugs}
    for d in clip.drugs:
        known.update(a.lower() for a in (d.aliases or ()))
    return [str(item.get("name", "")) for item in entities.get("drugs", []) or []
            if str(item.get("name", "")).lower() not in known]


def _spurious_allergies(clip: Clip, entities: Mapping[str, Any]) -> list[str]:
    known = {a.substance.lower() for a in clip.allergies}
    return [str(item.get("text", "")) for item in entities.get("allergies", []) or []
            if str(item.get("text", "")).lower() not in known]


def _score_entities(clip: Clip, entities: Mapping[str, Any]) -> dict[str, Any]:
    assigned, unclaimed = _assign_vitals(clip, entities)
    vitals = [(f"{v.kind}{'_'+v.note if v.note else ''}", assigned[i] is not None)
              for i, v in enumerate(clip.vitals)]
    extra_drugs = _spurious_drugs(clip, entities)
    extra_allergies = _spurious_allergies(clip, entities)
    drugs = []
    for drug in clip.drugs:
        found = _extracted_drug(entities, drug)
        # Polarity is part of identity for a prescription. `_extracted_drug`
        # matches on name alone, so a row the extractor marked "not given"
        # still counted as finding an active gold drug - which left the
        # scoreboard blind to the one failure the negation fix can introduce.
        polarity_ok = found is not None and bool(found.get("negated", False)) == drug.negated
        dose_ok = None
        if drug.dose is not None:
            dose_ok = bool(
                found
                and polarity_ok
                and found.get("dose") is not None
                and float(found["dose"]) == drug.dose
                and str(found.get("unit") or "").lower() == (drug.unit or "").lower()
            )
        drugs.append({"name": drug.name, "found": found is not None,
                      "polarity_ok": polarity_ok if found else None,
                      "dose_expected": drug.dose, "dose_ok": dose_ok})
    allergies = [{"substance": a.substance, "gold_negated": a.negated,
                  "outcome": _allergy_polarity(entities, a)} for a in clip.allergies]
    return {
        "vitals": vitals,
        "vitals_hit": sum(1 for _, ok in vitals if ok),
        "vitals_total": len(vitals),
        "drugs": drugs,
        "drugs_hit": sum(1 for d in drugs if d["found"] and d["polarity_ok"]),
        "drugs_wrong_polarity": sum(1 for d in drugs
                                    if d["found"] and not d["polarity_ok"]),
        "drugs_total": len(drugs),
        "doses_hit": sum(1 for d in drugs if d["dose_ok"]),
        "doses_total": sum(1 for d in drugs if d["dose_expected"] is not None),
        "allergies": allergies,
        "allergies_correct": sum(1 for a in allergies if a["outcome"] == "correct"),
        "allergies_total": len(allergies),
        # Precision. Recall alone is gameable: before these counters existed,
        # dumping every formulary name as a drug row scored 3/3 on clip 001.
        "vitals_spurious": len(unclaimed),
        "vitals_emitted": len(entities.get("vitals", []) or []),
        "drugs_spurious": len(extra_drugs),
        "drugs_spurious_names": extra_drugs,
        "drugs_emitted": len(entities.get("drugs", []) or []),
        "allergies_spurious": len(extra_allergies),
        "allergies_emitted": len(entities.get("allergies", []) or []),
    }


BOOTSTRAP_ROUNDS = 10_000


BOOTSTRAP_SEED = 1729


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (100 * (centre - half), 100 * (centre + half))


def cluster_bootstrap(per_clip: Sequence[tuple[int, int]], rounds: int = BOOTSTRAP_ROUNDS,
                      seed: int = BOOTSTRAP_SEED) -> tuple[float, float]:
    """95% interval for sum(hit)/sum(total), resampling whole clips."""
    clips = [c for c in per_clip if c[1]]
    if not clips:
        return (0.0, 0.0)
    rng = random.Random(seed)
    stats = []
    for _ in range(rounds):
        draw = [clips[rng.randrange(len(clips))] for _ in clips]
        stats.append(100 * sum(h for h, _ in draw) / sum(t for _, t in draw))
    stats.sort()
    return (stats[int(0.025 * rounds)], stats[int(0.975 * rounds) - 1])


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact p for the discordant pairs (a-only vs b-only)."""
    n = only_a + only_b
    if not n:
        return 1.0
    k = min(only_a, only_b)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def fact_hits(clip, score: Mapping[str, Any]) -> dict[tuple, bool]:
    """One boolean per gold fact, keyed so two runs can be paired."""
    hits: dict[tuple, bool] = {}
    for i, (_label, ok) in enumerate(score["vitals"]):
        hits[(clip.clip_id, "vital", i)] = bool(ok)
    for i, d in enumerate(score["drugs"]):
        hits[(clip.clip_id, "drug", i)] = bool(d["found"] and d["polarity_ok"])
        if d["dose_expected"] is not None:
            hits[(clip.clip_id, "dose", i)] = bool(d["dose_ok"])
    for i, a in enumerate(score["allergies"]):
        hits[(clip.clip_id, "allergy", i)] = a["outcome"] == "correct"
    return hits


def load_entities(runs_dir: Path, clip_id: str, denoiser: str) -> dict[str, Any] | None:
    """`<runs>/<clip>/entities.json` (medibytes) or `<runs>/<clip>/<denoiser>/` (older runs)."""
    for path in (runs_dir / clip_id / "entities.json", runs_dir / clip_id / denoiser / "entities.json"):
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def score_runs(runs_dir: Path, *, denoiser: str = "none", include_borderline: bool = False,
               current_only: bool = False, gold_path: str | Path | None = None) -> dict[str, Any]:
    gold = load(gold_path, include_borderline=include_borderline, current_only=current_only)
    clips: dict[str, Any] = {}
    hits: dict[tuple, bool] = {}
    missing = []
    for clip_id, clip in sorted(gold.items()):
        entities = load_entities(runs_dir, clip_id, denoiser)
        if entities is None:
            missing.append(clip_id)
            continue
        score = _score_entities(clip, entities)
        clips[clip_id] = score
        hits.update(fact_hits(clip, score))
    return {"gold": gold, "clips": clips, "hits": hits, "missing": missing}


def _slice(report: Mapping[str, Any], ids: Sequence[str]) -> dict[str, Any]:
    keys = ("vitals_hit", "vitals_total", "drugs_hit", "drugs_total", "doses_hit", "doses_total",
            "allergies_correct", "allergies_total", "vitals_spurious", "drugs_spurious",
            "drugs_wrong_polarity")
    tot = {k: 0 for k in keys}
    per_clip = []
    for cid in ids:
        sc = report["clips"].get(cid)
        if sc is None:
            continue
        for key in keys:
            tot[key] += sc[key]
        hit = sc["vitals_hit"] + sc["drugs_hit"] + sc["doses_hit"] + sc["allergies_correct"]
        n = sc["vitals_total"] + sc["drugs_total"] + sc["doses_total"] + sc["allergies_total"]
        per_clip.append((hit, n))
    k = sum(h for h, _ in per_clip)
    n = sum(t for _, t in per_clip)
    return {"hit": k, "total": n, "pct": round(100 * k / n, 1) if n else None,
            "wilson": tuple(round(x, 1) for x in wilson(k, n)),
            "cluster_bootstrap": tuple(round(x, 1) for x in cluster_bootstrap(per_clip)),
            "clips": len(per_clip), **tot}


def summarise(report: Mapping[str, Any], held_out: Collection[str] | None = None) -> dict[str, Any]:
    """`held_out` names the held-out clips; default: Phone40's split.json (even clips)."""
    ids = sorted(report["clips"])
    held_out = load_split(SPLIT_PATH) if held_out is None else held_out
    out = (lambda i: i in held_out)
    return {"in_sample": _slice(report, [i for i in ids if not out(i)]),
            "held_out": _slice(report, [i for i in ids if out(i)]),
            "missing_clips": report["missing"]}


def load_split(path: str | Path) -> set[str]:
    """Held-out clip ids from a JSON list or `{"held_out": [...]}`."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return set(data["held_out"] if isinstance(data, dict) else data)


def compare(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """a vs b on the facts both runs scored."""
    shared = a["hits"].keys() & b["hits"].keys()
    only_a = sorted(k for k in shared if a["hits"][k] and not b["hits"][k])
    only_b = sorted(k for k in shared if b["hits"][k] and not a["hits"][k])
    return {"facts_compared": len(shared), "a_only": only_a, "b_only": only_b,
            "net_a_minus_b": len(only_a) - len(only_b),
            "p_exact_mcnemar": round(mcnemar_exact(len(only_a), len(only_b)), 3)}


def misses(report: Mapping[str, Any]) -> list[str]:
    out = []
    for cid, sc in sorted(report["clips"].items()):
        bad = ([lbl for lbl, ok in sc["vitals"] if not ok]
               + [d["name"] + (" (wrong polarity)" if d["found"] and not d["polarity_ok"] else "")
                  for d in sc["drugs"] if not (d["found"] and d["polarity_ok"])]
               + [a["substance"] + ":" + a["outcome"] for a in sc["allergies"]
                  if a["outcome"] != "correct"])
        extra = []
        if sc["vitals_spurious"]:
            extra.append(f"spurious vitals {sc['vitals_spurious']}")
        if sc["drugs_spurious"]:
            extra.append("spurious drugs " + ",".join(sc["drugs_spurious_names"]))
        if bad or extra:
            out.append(f"{cid}: miss {bad}" + (f"  | {'; '.join(extra)}" if extra else ""))
    return out


def _line(name: str, s: Mapping[str, Any]) -> str:
    if not s["total"]:
        return f"  {name:10s} no clips scored"
    return (f"  {name:10s} {s['hit']}/{s['total']} = {s['pct']}%  "
            f"cluster-bootstrap {list(s['cluster_bootstrap'])}  wilson {list(s['wilson'])}  "
            f"[{s['clips']} clips]  vitals {s['vitals_hit']}/{s['vitals_total']} "
            f"drugs {s['drugs_hit']}/{s['drugs_total']}  spurious v={s['vitals_spurious']} "
            f"d={s['drugs_spurious']}  wrong-polarity={s['drugs_wrong_polarity']}")
