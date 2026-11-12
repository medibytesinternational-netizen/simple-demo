"""The pipeline: one audio file in, chart rows plus a 6-section discharge note out.

    1 preprocess   -> cleaned.wav                         (preprocessing.Preprocessor)
    2 medasr       -> transcript                          (asr.MedASRRecognizer)
    3 second_pass  -> second transcript                   (asr.WhisperSecondPass, small-int8)
    4 extract      -> normalise, regex + negation, fuzzy drug match, union of
                      second-pass rows, allergen reconcile
    5 llm_review   -> gpt-4.1 term validation, gpt-4.1 context repair, spans
    6 verify       -> deterministic fact checks
    7 discharge    -> gpt-4.1 parts analysis, note, gated, canonicalised, pre-filled, coverage-checked, schema-stamped

`Pipeline` depends only on the protocols in `ports.py`; `factory.build_pipeline`
supplies the real implementations.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

from .domain import ClipResult, StageEvent, StageName, StageState
from .errors import LLMError, SpeechModelUnavailable
from .extraction.allergens import reconcile_allergens
from .extraction.drug_matching import LAB_REQUEST, chart_name
from .extraction.entities import extract_entities
from .extraction.normalize import detect_lang_tag, normalize_text
from .extraction.second_pass import union_second_pass
from .extraction.spans import annotate_entity_spans
from .extraction.vocabulary import load_drug_list
from .llm.context_repair import apply_context_repair
from .llm.discharge import (
    DISCHARGE_SECTIONS,
    analyse_transcript,
    canonicalize_discharge,
    complete_coverage,
    extract_discharge,
    gate_discharge,
    merge_discharge,
    stamp_schema,
)
from .llm.term_validation import apply_validation
from .ports import AudioPreprocessor, LLMClient, ProgressSink, SpeechRecognizer
from .reference import drug_reference
from .verify import verify


def _ignore(event: StageEvent) -> None:
    return None


class _Stage:
    """Handle a stage body uses to set its detail line or mark itself degraded."""

    def __init__(self):
        self.detail = ""
        self.degraded = False

    def degrade(self, why: str) -> None:
        self.degraded = True
        self.detail = why[:200]


class _Tracker:
    def __init__(self, sink: ProgressSink):
        self._sink = sink
        self.events: list[StageEvent] = []

    @contextmanager
    def stage(self, name: StageName):
        self._sink(StageEvent(name, StageState.RUNNING))
        handle, t0 = _Stage(), time.perf_counter()
        try:
            yield handle
        except Exception as exc:
            event = StageEvent(name, StageState.FAILED, round(time.perf_counter() - t0, 2),
                               f"{type(exc).__name__}: {exc}"[:200])
            self.events.append(event)
            self._sink(event)
            raise
        state = StageState.DEGRADED if handle.degraded else StageState.DONE
        event = StageEvent(name, state, round(time.perf_counter() - t0, 2), handle.detail)
        self.events.append(event)
        self._sink(event)


def _empty_note(reason: str) -> dict:
    return {"sections": {k: {"items": []} for k in DISCHARGE_SECTIONS},
            "provenance": {"llm_engine": reason}}


class Pipeline:
    def __init__(self, preprocessor: AudioPreprocessor, first_pass: SpeechRecognizer,
                 second_pass: SpeechRecognizer, llm: LLMClient):
        self.preprocessor = preprocessor
        self.first_pass = first_pass
        self.second_pass = second_pass
        self.llm = llm

    def run(self, audio: Path, out_dir: Path, *, job_id: str,
            sink: ProgressSink = _ignore) -> ClipResult:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        cleaned = out_dir / "cleaned.wav"
        track = _Tracker(sink)

        with track.stage(StageName.PREPROCESS) as st:
            meta = self.preprocessor.clean(Path(audio), cleaned)
            st.detail = f"{meta['duration_s']:.1f} s, SNR {meta['snr_db']} dB"

        with track.stage(StageName.MEDASR) as st:
            stt = self.first_pass.transcribe(cleaned)
            norm = normalize_text(stt["text"])
            for seg in stt["segments"]:
                seg["lang"] = (detect_lang_tag(seg["text"]) if len(seg["text"]) < 200
                               else norm["lang_tag"])
            st.detail = f"{len(stt['text'].split())} words"

        alt, second_pass_error = None, ""
        with track.stage(StageName.SECOND_PASS) as st:
            try:
                alt = self.second_pass.transcribe(cleaned)
                st.detail = f"{len(alt['text'].split())} words"
            except SpeechModelUnavailable as exc:  # a second opinion is a bonus
                second_pass_error = f"{type(exc).__name__}: {exc}"[:120]
                st.degrade(second_pass_error)

        with track.stage(StageName.EXTRACT) as st:
            ent = extract_entities(stt["text"], norm["normalized_en"], stt["segments"])
            label = self.second_pass.label
            if alt is not None:
                ent = union_second_pass(ent, alt["text"], label, alt.get("segments") or [])
            else:
                ent["drug_second_pass"] = {"model": label, "error": second_pass_error}
            ent = reconcile_allergens(ent)  # the union can re-add an allergen as an order
            st.detail = (f"{len(ent.get('drugs', []))} drugs, {len(ent.get('vitals', []))} vitals, "
                         f"{len(ent.get('allergies', []))} allergies")

        with track.stage(StageName.LLM_REVIEW) as st:
            t0 = time.perf_counter()
            ent = apply_validation(ent, llm=self.llm)
            if ent.get("term_validator"):
                ent["term_validator_seconds"] = round(time.perf_counter() - t0, 3)
            known = {d["name"].lower() for d in load_drug_list()}
            ent = apply_context_repair(
                ent, norm["normalized_en"], llm=self.llm,
                chart_name=lambda n: chart_name(n, known),
                stopwords=drug_reference.STOPWORDS,
                skip_sentence=lambda sent: bool(LAB_REQUEST.search(sent)))
            ent = annotate_entity_spans(ent, norm["normalized_en"])
            st.detail, problem = _llm_review_summary(ent)
            if problem:
                st.degrade(problem)

        transcript = {"job_id": job_id, "text": stt["text"], "language": norm["lang_tag"],
                      "segments": stt["segments"], "normalized_en": norm["normalized_en"],
                      "normalizations": norm["normalizations"], "stt_engine": stt["engine"],
                      "stt_provenance": stt["stt_provenance"],
                      "second_pass": ({"engine": alt["engine"], "text": alt["text"]}
                                      if alt is not None else None)}
        entities = {"job_id": job_id, **ent}

        with track.stage(StageName.VERIFY) as st:
            entities["verify"] = verify(transcript, entities)
            summary = entities["verify"]["summary"]
            st.detail = f"{summary.get('total', 0)} facts checked"

        with track.stage(StageName.DISCHARGE) as st:
            entities["discharge"] = self._discharge(transcript, entities["verify"], st)

        return ClipResult(clean_meta=meta, transcript=transcript, entities=entities,
                          stages=track.events)

    def _discharge(self, transcript: dict, verified: dict, st: _Stage) -> dict:
        text, norm = transcript.get("text", ""), transcript.get("normalized_en", "")
        # The checklist of dictated parts; without it, coverage falls back to cues.
        parts, analysis_error = None, ""
        try:
            parts = analyse_transcript(text, llm=self.llm)
        except (LLMError, ValueError, LookupError) as exc:
            analysis_error = f"analysis skipped ({type(exc).__name__})"
        try:
            raw = extract_discharge(text, norm, transcript.get("segments", []), verified,
                                    llm=self.llm, parts=parts)
        except LLMError as exc:
            st.degrade(f"gpt-4.1 note not written: {exc}")
            return stamp_schema(_empty_note(f"discharge-skipped ({type(exc).__name__}: {exc})"))
        gated = gate_discharge(raw, text, norm, verified)
        locked = canonicalize_discharge(gated, verified)
        merged = merge_discharge(verified, locked, text, norm)
        note = stamp_schema(complete_coverage(merged, text, norm, verified, llm=self.llm,
                                              parts=parts))
        items = sum(len(s["items"]) for s in note["sections"].values())
        coverage = note["provenance"]["coverage"]
        unused = sum(len(v) for v in coverage["unused"].values())
        st.detail = (f"{items} items, {unused} dictated parts not written, "
                     f"schema {note['provenance'].get('schema')}")
        if coverage["missing"]:
            st.degrade(f"{st.detail}; empty: {', '.join(coverage['missing'])}")
        if analysis_error:
            st.degrade(f"{st.detail}; {analysis_error}")
        return note


def _llm_review_summary(ent: dict) -> tuple[str, str]:
    """(detail, problem) for the gpt-4.1 review stage; problem is "" when all calls ran."""
    rows = [d for d in ent.get("drugs", []) if isinstance(d, dict) and d.get("validation")]
    skipped = [d for d in rows if d["validation"].get("status") == "skipped"]
    repair = ent.get("context_repair") or {}
    detail = (f"{len(rows)} validated, {len(repair.get('repaired', []))} repaired, "
              f"{repair.get('calls', 0)} repair calls")
    problems = []
    if skipped:
        problems.append(f"{len(skipped)} validation(s) skipped: "
                        f"{skipped[0]['validation'].get('reason', '')}")
    if repair.get("status") == "skipped":
        problems.append(f"context repair skipped: {repair.get('reason', '')}")
    elif repair.get("errors"):
        problems.append(f"context repair errors: {repair['errors'][0]}")
    return detail, "; ".join(problems)
