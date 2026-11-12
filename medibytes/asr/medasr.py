"""Stage 2 - MedASR (google/medasr) first-pass speech recognition."""
from __future__ import annotations

import contextlib
import re
import wave
from importlib import metadata as importlib_metadata
from pathlib import Path

import numpy as np

from ..config import C1
from ..errors import SpeechModelUnavailable

# ---- MedASR (google/medasr) STT backend ----------------------------------
# A CTC medical-dictation model, not a seq2seq decoder: it emits one unsegmented
# string with no timestamps and no language id, so the segment list below is a
# single span with evenly-spaced word times and `word_timestamps` is recorded as
# False.  Nothing else in the contract changes.
MEDASR_MODEL_ID = C1.asr.medasr_model_id


# MedASR is a dictation model: it does not emit punctuation characters, it emits
# the spoken command that produced them (`{period}`), the report section the
# dictation is in (`[FINDINGS]`), and its own CTC end token.  Left alone, every
# one of those becomes a spurious word downstream - `{period}` tokenises to
# "period" and `</s>` to "s" - so the markup is resolved here, once, before any
# consumer sees the text.  The punctuation map is what the model actually
# produced on this project's audio; an unrecognised `{directive}` is dropped
# rather than guessed at, and section headers are dropped because the
# extractor reads prose, not report structure.
MEDASR_PUNCTUATION = {
    "period": ".",
    "full stop": ".",
    "comma": ",",
    "colon": ":",
    "semicolon": ";",
    "question mark": "?",
    "exclamation point": "!",
    "hyphen": "-",
    "dash": "-",
    "slash": "/",
    "apostrophe": "'",
    "open paren": "(",
    "close paren": ")",
    "open parenthesis": "(",
    "close parenthesis": ")",
    "open quote": '"',
    "close quote": '"',
    "new paragraph": "\n\n",
    "new line": "\n",
    "next line": "\n",
}


_MEDASR_DIRECTIVE = re.compile(r"\{\s*([^{}]*?)\s*\}")


_MEDASR_SECTION = re.compile(r"\[\s*[^\[\]]*\s*\]")


_MEDASR_SPECIAL = re.compile(r"</?s>|<unk>|<pad>|<epsilon>|<extra_id_\d+>")


def medasr_detokenize(text):
    """Resolve MedASR's dictation markup into ordinary punctuated prose."""
    out = _MEDASR_SPECIAL.sub(" ", str(text))
    out = _MEDASR_SECTION.sub(" ", out)
    out = _MEDASR_DIRECTIVE.sub(
        lambda m: MEDASR_PUNCTUATION.get(m.group(1).strip().lower(), " "), out
    )
    # Unmatched brackets survive a truncated or mis-decoded directive.
    out = re.sub(r"[\[\]{}]", " ", out)
    out = re.sub(r"\s+([.,:;?!])", r"\1", out)
    out = re.sub(r"[ \t]+", " ", out)
    return out.strip()


def _model_attribute(model, *names):
    for name in names:
        value = getattr(model, name, None)
        if value is not None and str(value):
            return str(value)
    return None


def _medasr_segments(text, duration_s):
    """One span over the whole clip; word times interpolated, never measured."""
    words = text.split()
    if not words:
        return []
    step = duration_s / len(words) if duration_s > 0 else 0.32
    return [{
        "id": 0,
        "text": text,
        "start": 0.0,
        "end": round(duration_s, 2),
        "lang": "en",
        "confidence": 0.9,
        "words": [{"w": w, "s": round(i * step, 2), "e": round((i + 1) * step, 2)}
                  for i, w in enumerate(words)],
    }]


def _transformers_version():
    try:
        return importlib_metadata.version("transformers")
    except importlib_metadata.PackageNotFoundError:
        return None


def _read_pcm16(wav: Path) -> tuple[np.ndarray, int, float]:
    """(mono float32 samples, sample rate, duration) of a PCM16 WAV."""
    with contextlib.closing(wave.open(str(wav), "rb")) as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        frames = handle.readframes(handle.getnframes())
        duration_s = handle.getnframes() / float(rate)
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    return pcm, rate, duration_s


class MedASRRecognizer:
    """google/medasr through the transformers ASR pipeline, loaded once.

    A CTC medical-dictation model: one unsegmented string with no timestamps,
    so the segment list is a single span with interpolated word times. Raw audio
    is passed (not a filename) so no system `ffmpeg` is needed.
    """

    label = "medasr"

    def __init__(self, device: int | None = None):
        self._device = device
        self._pipe = None

    def _pipeline(self):
        if self._pipe is None:
            try:
                import torch
                from transformers import pipeline as hf_pipeline

                device = self._device
                if device is None:
                    device = 0 if torch.cuda.is_available() else -1
                self._pipe = hf_pipeline("automatic-speech-recognition",
                                         model=MEDASR_MODEL_ID, device=device)
            except Exception as exc:
                raise SpeechModelUnavailable(
                    f"MedASR ({MEDASR_MODEL_ID}) could not be loaded: "
                    f"{type(exc).__name__}: {exc}") from exc
        return self._pipe

    def transcribe(self, wav: Path) -> dict:
        import torch

        pipe = self._pipeline()
        resolved = getattr(pipe, "device", None)
        device_name = str(resolved) if resolved is not None else "cpu"
        pcm, rate, duration_s = _read_pcm16(wav)
        try:
            raw_text = str(pipe({"array": pcm, "sampling_rate": rate},
                                chunk_length_s=C1.asr.medasr_chunk_s,
                                stride_length_s=C1.asr.medasr_stride_s)["text"])
        except Exception as exc:
            raise SpeechModelUnavailable(f"MedASR failed: {type(exc).__name__}: {exc}") from exc
        text = medasr_detokenize(raw_text)
        provenance = {
            "provider": "transformers",
            "requested_model": "medasr",
            "actual_model": MEDASR_MODEL_ID,
            "device": device_name,
            "compute_type": str(getattr(pipe.model, "dtype", torch.float32)),
            "word_timestamps": False,
            "temperature": 0.0,
            "beam_size": None,
            "runtime_version": _transformers_version(),
            "model_hash": None,
            "model_snapshot": _model_attribute(pipe.model, "name_or_path"),
            "is_mock": False,
        }
        return {"text": text, "raw_text": raw_text,
                "segments": _medasr_segments(text, duration_s),
                "engine": f"medasr:{MEDASR_MODEL_ID}@{device_name}",
                "language": "en", "stt_provenance": provenance}
