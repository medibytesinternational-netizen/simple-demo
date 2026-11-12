"""Stage 3 - faster-whisper small (int8, CPU, greedy) as the second listener.

MedASR and small-int8 fail on different words: on held-out clips their union
recovered six more gold drugs than either alone. This decoder's transcript is
used only to add rows the first pass missed (see `extraction.second_pass`).
"""
from __future__ import annotations

import re
from importlib import metadata as importlib_metadata
from pathlib import Path

from ..config import C1
from ..errors import SpeechModelUnavailable


def _runtime_version(module) -> str | None:
    version = getattr(module, "__version__", None)
    if version:
        return str(version)
    try:
        return importlib_metadata.version("faster-whisper")
    except importlib_metadata.PackageNotFoundError:
        return None


def _model_attribute(model, *names):
    for name in names:
        value = getattr(model, name, None)
        if value is not None and str(value):
            return str(value)
    return None


class WhisperSecondPass:
    """faster-whisper `small` in int8 on CPU with greedy decoding, loaded once."""

    label = C1.asr.second_pass_label  # "small-int8": the name notes and provenance use

    def __init__(self):
        self._model = None
        self._module = None

    def _load(self):
        if self._model is None:
            try:
                import faster_whisper
                from faster_whisper import WhisperModel

                self._module = faster_whisper
                self._model = WhisperModel(C1.asr.whisper_size, device=C1.asr.whisper_device,
                                           compute_type=C1.asr.whisper_compute_type)
            except Exception as exc:
                raise SpeechModelUnavailable(
                    f"faster-whisper {C1.asr.whisper_size} could not be loaded: "
                    f"{type(exc).__name__}: {exc}") from exc
        return self._model

    def transcribe(self, wav: Path) -> dict:
        model = self._load()
        decode = dict(C1.asr.whisper_decode)
        try:
            segments, info = model.transcribe(str(wav), **decode)
            segs, full = [], []
            for i, s in enumerate(segments):
                full.append(s.text.strip())
                segs.append({
                    "id": i, "text": s.text.strip(), "start": round(s.start, 2),
                    "end": round(s.end, 2), "lang": getattr(info, "language", "en"),
                    "confidence": (round(float(getattr(s, "avg_logprob", -0.2)) * -1 + 0.7, 2)
                                   if hasattr(s, "avg_logprob") else 0.88),
                    "words": [{"w": w.word, "s": round(w.start, 2), "e": round(w.end, 2)}
                              for w in (s.words or [])]})
                # hallucination guard: a thank-you loop on silence is not speech
                if re.search(r"(thank you\s*){3,}", s.text, re.I):
                    segs[-1]["confidence"] = 0.2
        except Exception as exc:
            raise SpeechModelUnavailable(
                f"faster-whisper failed: {type(exc).__name__}: {exc}") from exc
        provenance = {
            "provider": "faster-whisper",
            "requested_model": self.label,
            "actual_model": C1.asr.whisper_size,
            "device": C1.asr.whisper_device,
            "compute_type": C1.asr.whisper_compute_type,
            "word_timestamps": True,
            "temperature": decode["temperature"],
            "beam_size": decode["beam_size"],
            "decode_kwargs": decode,
            "runtime_version": _runtime_version(self._module),
            "model_hash": _model_attribute(model, "model_sha256", "model_hash"),
            "model_snapshot": _model_attribute(model, "model_snapshot", "snapshot", "model_path"),
            "is_mock": False,
        }
        engine = (f"faster-whisper:{C1.asr.whisper_size}-{C1.asr.whisper_device}-"
                  f"{C1.asr.whisper_compute_type}")
        return {"text": " ".join(full), "segments": segs, "engine": engine,
                "language": getattr(info, "language", "en"), "stt_provenance": provenance}
