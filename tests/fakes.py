"""Test doubles for every port of the pipeline."""
from __future__ import annotations

import json
from pathlib import Path

TEXT = ("Patient has fever and cough. Temperature 101 degrees Fahrenheit, pulse 92. "
        "Give paracetamol 500 mg twice daily for 3 days. No known drug allergy. "
        "Review after one week.")


class FakePreprocessor:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def clean(self, src: Path, dst: Path) -> dict:
        if self.error:
            raise self.error
        Path(dst).write_bytes(b"RIFF")
        return {"duration_s": 12.0, "sample_rate": 16000, "snr_db": 25.0, "vad_ratio": 0.8,
                "rms_dbfs_before": -26.0, "rms_dbfs_after": -20.0, "input_sha256": "0" * 64}


class FakeRecognizer:
    def __init__(self, label: str, text: str = TEXT, error: Exception | None = None):
        self.label, self.text, self.error = label, text, error

    def transcribe(self, wav: Path) -> dict:
        if self.error:
            raise self.error
        return {"text": self.text, "engine": f"fake:{self.label}", "language": "en",
                "segments": [{"id": 0, "text": self.text}],
                "stt_provenance": {"actual_model": self.label, "is_mock": False}}


class FakeLLM:
    """Answers every stage with a reply its parser accepts; or fails as told."""

    model = "gpt-4.1"

    def __init__(self, error: Exception | None = None, ok: bool = True):
        self.error, self.ok, self.stages = error, ok, []

    def available(self):
        return (True, "") if self.ok else (False, "OPENAI_API_KEY is not set")

    def complete_json(self, prompt, *, timeout, max_tokens, stage):
        self.stages.append(stage)
        if self.error:
            raise self.error
        if stage == "discharge_analyse":
            return json.dumps({"parts": [
                {"quote": "Patient has fever and cough.", "section": "present_illness"}]})
        if stage == "discharge":
            return json.dumps({"present_illness": {"items": [
                {"text": "fever", "source_sentence": "Patient has fever and cough.",
                 "seg_id": 0, "confidence": 0.9}]}})
        return json.dumps({"decision": "none", "status": "ambiguous", "confidence": 0.1,
                           "semantic_confidence_score": 0.1, "chosen_token": "", "reason": "x"})
