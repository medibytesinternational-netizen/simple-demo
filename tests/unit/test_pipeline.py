"""Pipeline orchestration with fakes behind every port: order, states, failure handling."""
from __future__ import annotations

import pytest

from medibytes.domain import STAGE_ORDER, StageName, StageState
from medibytes.errors import AudioRejected, LLMCallFailed, LLMUnavailable, SpeechModelUnavailable
from medibytes.output import FILES, write_result
from medibytes.pipeline import Pipeline
from tests.fakes import FakeLLM, FakePreprocessor, FakeRecognizer


def _pipeline(**kw) -> Pipeline:
    return Pipeline(preprocessor=kw.get("pre", FakePreprocessor()),
                    first_pass=kw.get("first", FakeRecognizer("medasr")),
                    second_pass=kw.get("second", FakeRecognizer("small-int8")),
                    llm=kw.get("llm", FakeLLM()))


def _run(tmp_path, **kw):
    events = []
    result = _pipeline(**kw).run(tmp_path / "in.wav", tmp_path / "out", job_id="j1",
                                 sink=events.append)
    return result, events


def test_all_seven_stages_run_in_order_and_report_running_then_done(tmp_path):
    result, events = _run(tmp_path)
    assert [e.stage for e in result.stages] == list(STAGE_ORDER)
    assert all(e.state is StageState.DONE for e in result.stages), result.stage_json()
    running = [e.stage for e in events if e.state is StageState.RUNNING]
    assert running == list(STAGE_ORDER)
    assert all(e.seconds is not None for e in result.stages)


def test_result_carries_chart_verify_and_a_valid_six_section_note(tmp_path):
    result, _ = _run(tmp_path)
    names = [d["name"] for d in result.entities["drugs"]]
    assert "paracetamol" in names
    assert result.verify["facts"]
    note = result.discharge
    assert set(note["sections"]) == {"present_illness", "examination_findings",
                                     "previous_diagnosis", "plan_of_management",
                                     "diet_instructions", "general_instructions"}
    assert note["provenance"]["schema"] == "valid"
    plan = [i["text"] for i in note["sections"]["plan_of_management"]["items"]]
    assert any("paracetamol 500 mg" in t for t in plan)  # pre-filled from the verified fact
    assert result.transcript["job_id"] == result.entities["job_id"] == "j1"
    assert result.transcript["second_pass"]["engine"] == "fake:small-int8"


def test_output_writer_writes_every_file(tmp_path):
    result, _ = _run(tmp_path)
    written = write_result(result, tmp_path / "out", "in.wav")
    assert written == list(FILES)
    for name in FILES:
        assert (tmp_path / "out" / name).is_file()
    assert "## Discharge note" in (tmp_path / "out" / "report.md").read_text(encoding="utf-8")


def test_rejected_audio_fails_the_preprocess_stage_and_raises(tmp_path):
    events = []
    with pytest.raises(AudioRejected):
        _pipeline(pre=FakePreprocessor(AudioRejected("422 NO_AUDIO: silent"))).run(
            tmp_path / "in.wav", tmp_path / "out", job_id="j", sink=events.append)
    assert events[-1].stage is StageName.PREPROCESS
    assert events[-1].state is StageState.FAILED
    assert "NO_AUDIO" in events[-1].detail


def test_medasr_failure_fails_the_run(tmp_path):
    with pytest.raises(SpeechModelUnavailable):
        _run(tmp_path, first=FakeRecognizer("medasr", error=SpeechModelUnavailable("no weights")))


def test_second_pass_failure_degrades_but_the_run_completes(tmp_path):
    result, _ = _run(tmp_path, second=FakeRecognizer(
        "small-int8", error=SpeechModelUnavailable("faster-whisper missing")))
    states = {e.stage: e.state for e in result.stages}
    assert states[StageName.SECOND_PASS] is StageState.DEGRADED
    assert states[StageName.DISCHARGE] is StageState.DONE
    assert "faster-whisper missing" in result.entities["drug_second_pass"]["error"]
    assert result.transcript["second_pass"] is None


def test_unreachable_llm_degrades_both_llm_stages_and_writes_an_empty_note(tmp_path):
    result, _ = _run(tmp_path, llm=FakeLLM(error=LLMUnavailable("cannot reach api")))
    states = {e.stage: e.state for e in result.stages}
    assert states[StageName.DISCHARGE] is StageState.DEGRADED
    note = result.discharge
    assert all(not s["items"] for s in note["sections"].values())
    assert "discharge-skipped" in note["provenance"]["llm_engine"]
    assert note["provenance"]["schema"] == "valid"


def test_a_failed_llm_call_never_changes_a_chart_row(tmp_path):
    clean, _ = _run(tmp_path / "a")
    failed, _ = _run(tmp_path / "b", llm=FakeLLM(error=LLMCallFailed("HTTP 500")))
    strip = lambda rows: [{k: v for k, v in r.items() if k not in ("validation", "note")}  # noqa: E731
                          for r in rows]
    assert strip(failed.entities["drugs"]) == strip(clean.entities["drugs"])


def test_a_failed_analysis_falls_back_to_cues_and_still_writes_the_note(tmp_path):
    class NoAnalysis(FakeLLM):
        def complete_json(self, prompt, *, timeout, max_tokens, stage):
            if stage == "discharge_analyse":
                self.stages.append(stage)
                return "not json"
            return super().complete_json(prompt, timeout=timeout, max_tokens=max_tokens, stage=stage)
    result, _ = _run(tmp_path, llm=NoAnalysis())
    stage = next(e for e in result.stages if e.stage is StageName.DISCHARGE)
    assert stage.state is StageState.DEGRADED and "analysis skipped" in stage.detail
    assert result.discharge["provenance"]["coverage"]["source"] == "cues"
    assert any(s["items"] for s in result.discharge["sections"].values())
