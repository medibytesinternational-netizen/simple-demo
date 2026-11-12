"""Stage 1: decode, resample, level-normalise, reject unusable audio, deterministic output."""
from __future__ import annotations

import contextlib
import wave
from pathlib import Path

import numpy as np
import pytest

from medibytes.errors import AudioRejected
from medibytes.preprocessing.audio import _antialias_lowpass, _resample_linear
from medibytes.preprocessing.preprocessor import STEPS, Preprocessor


def _write_wav(path: Path, samples: np.ndarray, rate: int, channels: int = 1) -> Path:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with contextlib.closing(wave.open(str(path), "wb")) as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())
    return path


def _speechlike(seconds: float, rate: int) -> np.ndarray:
    """Amplitude-modulated tones: loud enough, and mostly above the VAD threshold."""
    t = np.arange(int(seconds * rate)) / rate
    carrier = np.sin(2 * np.pi * 220 * t) + 0.5 * np.sin(2 * np.pi * 660 * t)
    envelope = 0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)
    return (0.3 * carrier * envelope).astype(np.float32)


def _read(path: Path) -> tuple[int, int, int]:
    with contextlib.closing(wave.open(str(path), "rb")) as wav:
        return wav.getframerate(), wav.getnchannels(), wav.getsampwidth()


def test_output_is_16k_mono_pcm16_with_measurements(tmp_path):
    src = _write_wav(tmp_path / "in.wav", _speechlike(2.0, 16000), 16000)
    meta = Preprocessor().clean(src, tmp_path / "cleaned.wav")
    assert _read(tmp_path / "cleaned.wav") == (16000, 1, 2)
    assert meta["sample_rate"] == 16000 and meta["channels"] == 1
    assert meta["duration_s"] == pytest.approx(2.0, abs=1e-3)
    assert meta["rms_dbfs_after"] == pytest.approx(-20.0, abs=0.1)  # 0.1 RMS target
    assert meta["denoiser"] == "none"
    assert meta["steps"] == list(STEPS)
    assert 0.0 < meta["vad_ratio"] <= 1.0


def test_same_input_gives_byte_identical_output(tmp_path):
    src = _write_wav(tmp_path / "in.wav", _speechlike(1.5, 22050), 22050)
    a = Preprocessor().clean(src, tmp_path / "a.wav")
    b = Preprocessor().clean(src, tmp_path / "b.wav")
    assert a["output_sha256"] == b["output_sha256"]
    assert (tmp_path / "a.wav").read_bytes() == (tmp_path / "b.wav").read_bytes()


def test_stereo_44k_is_downmixed_and_resampled(tmp_path):
    mono = _speechlike(1.0, 44100)
    stereo = np.stack([mono, mono], axis=1).reshape(-1)
    src = _write_wav(tmp_path / "in.wav", stereo, 44100, channels=2)
    meta = Preprocessor().clean(src, tmp_path / "cleaned.wav")
    assert _read(tmp_path / "cleaned.wav") == (16000, 1, 2)
    assert meta["sample_count"] == 16000


def test_peak_is_held_under_the_ceiling(tmp_path):
    spiky = _speechlike(1.0, 16000) * 0.05
    # One click ~20x the RMS: raising RMS to 0.1 would push it past full scale,
    # so the peak ceiling must pull the whole signal down.
    spiky[100] = 0.15
    src = _write_wav(tmp_path / "in.wav", spiky, 16000)
    meta = Preprocessor().clean(src, tmp_path / "cleaned.wav")
    assert meta["peak_scale"] < 1.0
    assert meta["peak_after"] <= 0.98 + 1e-6
    assert meta["clipping_count"] == 0


@pytest.mark.parametrize("samples, message", [
    (np.zeros(16000, dtype=np.float32), "NO_AUDIO"),             # digital silence
    (_speechlike(0.3, 16000), "NO_AUDIO"),                          # shorter than 0.6 s
])
def test_unusable_audio_is_rejected(tmp_path, samples, message):
    src = _write_wav(tmp_path / "in.wav", samples, 16000)
    with pytest.raises(AudioRejected, match=message):
        Preprocessor().clean(src, tmp_path / "cleaned.wav")


def test_missing_and_empty_files_are_rejected(tmp_path):
    with pytest.raises(AudioRejected, match="404"):
        Preprocessor().clean(tmp_path / "absent.wav", tmp_path / "cleaned.wav")
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    with pytest.raises(AudioRejected, match="empty"):
        Preprocessor().clean(empty, tmp_path / "cleaned.wav")


def _band_energy(signal: np.ndarray, rate: int, low: float, high: float) -> float:
    spectrum = np.abs(np.fft.rfft(signal)) ** 2
    freqs = np.fft.rfftfreq(signal.size, 1.0 / rate)
    return float(spectrum[(freqs >= low) & (freqs <= high)].sum())


def test_downsampling_does_not_fold_supersonic_tone_into_speech_band():
    """A 12 kHz tone at 44.1 kHz must not reappear at 4 kHz after the drop to 16 kHz."""
    source_rate, target_rate = 44100, 16000
    t = np.arange(source_rate, dtype=np.float64) / source_rate
    tone = np.sin(2.0 * np.pi * 12000 * t).astype(np.float32)
    reference = np.sin(2.0 * np.pi * 1000.0 * t).astype(np.float32)
    passband = _band_energy(_resample_linear(reference, source_rate, target_rate),
                            target_rate, 900.0, 1100.0)
    alias = _band_energy(_resample_linear(tone, source_rate, target_rate),
                         target_rate, 3800.0, 4200.0)
    assert passband > 0.0
    assert alias / passband < 1e-4


def test_antialias_filter_preserves_length_contract():
    audio = np.random.default_rng(0).standard_normal(44100).astype(np.float32)
    assert _antialias_lowpass(audio, 44100, 16000).size == audio.size
    assert _resample_linear(audio, 44100, 16000).size == 16000
    assert _resample_linear(audio[:16000], 16000, 44100).size == 44100
