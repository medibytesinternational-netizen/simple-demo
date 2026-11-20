"""The seams the pipeline depends on (dependency inversion).

`Pipeline` talks only to these protocols; `factory.build_pipeline` wires the one
concrete implementation of each. Tests substitute recorded transcripts and a
replayed gpt-4.1 through the same seams.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

JSON = dict[str, Any]


class AudioPreprocessor(Protocol):
    def clean(self, src: Path, dst: Path) -> JSON:
        """Write a 16 kHz mono PCM16 WAV to `dst`; return its measurements."""


class SpeechRecognizer(Protocol):
    label: str  # how notes and provenance name this decoder, e.g. "small-int8"

    def transcribe(self, wav: Path) -> JSON:
        """{text, segments, engine, language, stt_provenance} for one clean WAV."""


class LLMClient(Protocol):
    model: str

    def available(self) -> tuple[bool, str]:
        """(ok, reason) - can a call be made right now?"""

    def complete_json(self, prompt: str, *, timeout: float, max_tokens: int,
                      stage: str) -> str:
        """The model's reply text (expected to hold one JSON object).

        Raises `errors.LLMUnavailable` (or `LLMTimeout`) on any transport failure.
        """


class ProgressSink(Protocol):
    def __call__(self, event: Any) -> None:
        """Receive one `domain.StageEvent`."""
