"""Signal primitives for Stage 1: decode, resample, level, VAD, SNR, hashing.

numpy-only on purpose (no scipy); every step is deterministic so the cleaned WAV
is byte-identical for the same input file.
"""
from __future__ import annotations

import contextlib
import hashlib
import math
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from ..config import C1
from ..errors import AudioRejected

TARGET_SR = C1.audio.target_sample_rate


MAX_BYTES = C1.audio.max_bytes


MAX_SECONDS = C1.audio.max_seconds


def _wav_info(path: Path):
    """Return WAV geometry, or ``None`` for non-WAV input."""
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as wav:
            frames = wav.getnframes()
            sample_rate = wav.getframerate()
            channels = wav.getnchannels()
            duration = frames / float(sample_rate) if sample_rate else 0.0
            return frames, sample_rate, channels, duration
    except (OSError, wave.Error):
        return None


def _soundfile_info(path: Path):
    try:
        import soundfile as sf

        info = sf.info(str(path))
        return info.frames, info.samplerate, info.channels, info.duration
    except Exception:
        return None


def check_audio(path: Path) -> dict:
    """Validate the receive-stage size and duration guards."""
    path = Path(path)
    if not path.is_file():
        raise AudioRejected(f"404 NOT_FOUND: {path}")
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise AudioRejected(f"413 TOO_BIG: {size} bytes > 100MB")
    if size == 0:
        raise AudioRejected("422 NO_AUDIO: empty file")

    info = _wav_info(path) or _soundfile_info(path)
    if info is None:
        try:
            import imageio_ffmpeg  # noqa: F401
        except Exception as exc:
            raise AudioRejected(
                "422 DECODE_FAIL: need wav or pip install imageio-ffmpeg "
                f"({exc})"
            ) from exc
        return {"size": size, "duration": None, "note": "non-wav, will convert via ffmpeg"}

    _, _, _, duration = info
    if duration > MAX_SECONDS:
        raise AudioRejected(f"413 TOO_LONG: {duration:.1f}s > 30min")
    if duration < 0.6:
        raise AudioRejected("422 NO_AUDIO: <0.6s")
    return {"size": size, "duration": duration}


def _antialias_lowpass(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Windowed-sinc low-pass at the target Nyquist, for use before decimation.

    Without this, ``np.interp`` decimation folds every component above the
    target Nyquist back into the speech band -- a 12kHz component in 44.1kHz
    input reappears at 4kHz after a drop to 16kHz, squarely on top of speech.
    Kept numpy-only on purpose: scipy is not a dependency.  ``mode="same"``
    with edge padding preserves the exact length the callers' contracts assume.
    """
    taps = 101
    if audio.size < taps:
        return np.asarray(audio, dtype=np.float32)
    cutoff = 0.5 * target_rate / source_rate  # cycles/sample, target Nyquist
    offsets = np.arange(taps) - (taps - 1) / 2.0
    kernel = 2.0 * cutoff * np.sinc(2.0 * cutoff * offsets) * np.hamming(taps)
    kernel /= kernel.sum()
    pad = taps // 2
    padded = np.pad(np.asarray(audio, dtype=np.float64), pad, mode="edge")
    return np.convolve(padded, kernel, mode="valid").astype(np.float32)


def _resample_linear(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Duration-preserving endpoint resampling used at the shared boundary."""
    if source_rate == target_rate:
        return np.asarray(audio, dtype=np.float32).copy()
    if audio.size == 0:
        return np.empty(0, dtype=np.float32)
    if target_rate < source_rate:
        audio = _antialias_lowpass(audio, source_rate, target_rate)
    target_length = max(1, int(round(audio.size * target_rate / source_rate)))
    if audio.size == 1:
        return np.full(target_length, float(audio[0]), dtype=np.float32)
    source_positions = np.arange(audio.size, dtype=np.float64)
    target_positions = np.linspace(0.0, audio.size - 1, target_length, dtype=np.float64)
    return np.interp(target_positions, source_positions, audio).astype(np.float32)


def _decode_pcm(raw: bytes, sample_width: int) -> np.ndarray:
    if sample_width == 1:
        return np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
    if sample_width == 2:
        return np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if sample_width == 3:
        octets = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        values = octets[:, 0].astype(np.int32)
        values |= octets[:, 1].astype(np.int32) << 8
        values |= octets[:, 2].astype(np.int32) << 16
        values = np.where(values & 0x800000, values - 0x1000000, values)
        return values.astype(np.float32) / float(2**23)
    if sample_width == 4:
        return np.frombuffer(raw, dtype="<i4").astype(np.float32)
    raise AudioRejected(f"422 DECODE_FAIL: unsupported WAV sample width {sample_width}")


def decode_mono_16k(path: Path, target_sr: int = TARGET_SR) -> tuple[np.ndarray, int]:
    """Decode any supported input to mono float32 at the shared rate."""
    path = Path(path)
    info = _wav_info(path)
    if info is not None:
        _, source_rate, channels, _ = info
        with contextlib.closing(wave.open(str(path), "rb")) as wav:
            raw = wav.readframes(wav.getnframes())
            sample_width = wav.getsampwidth()
        samples = _decode_pcm(raw, sample_width)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        if sample_width == 1:
            audio = (samples - 128.0) / 128.0
        else:
            divisor = float(2 ** (8 * sample_width - 1))
            audio = samples / divisor
        return _resample_linear(audio, source_rate, target_sr), target_sr

    try:
        import imageio_ffmpeg

        executable = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        try:
            subprocess.run(
                [executable, "-y", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(target_sr), str(temporary_path)],
                check=True,
                capture_output=True,
            )
            return decode_mono_16k(temporary_path, target_sr)
        finally:
            temporary_path.unlink(missing_ok=True)
    except Exception as exc:
        raise AudioRejected(
            "422 DECODE_FAIL: need wav or pip install imageio-ffmpeg "
            f"({exc})"
        ) from exc


def save_pcm16_wav(path: Path, audio: np.ndarray, sample_rate: int = TARGET_SR) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    pcm = (values * 32767.0).astype(np.int16)
    with contextlib.closing(wave.open(str(path), "wb")) as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def rms_vad(audio: np.ndarray, sample_rate: int, frame_ms: int = 30, threshold: float = 0.02):
    """Return a diagnostic RMS speech mask without trimming the timeline."""
    if audio.size == 0:
        return np.zeros(0, dtype=bool), 0.0
    frame_length = max(1, int(sample_rate * frame_ms / 1000))
    frame_count = audio.size // frame_length
    if frame_count == 0:
        return np.ones(audio.size, dtype=bool), 1.0
    frames = audio[: frame_count * frame_length].reshape(frame_count, frame_length)
    frame_rms = np.sqrt(np.mean(np.square(frames), axis=1))
    speech_frames = frame_rms >= threshold
    if not speech_frames.any():
        keep = max(1, frame_count // 5)
        speech_frames[np.argsort(frame_rms)[-keep:]] = True
    mask = np.repeat(speech_frames, frame_length)
    remainder = audio.size - mask.size
    if remainder:
        mask = np.concatenate((mask, np.full(remainder, speech_frames[-1], dtype=bool)))
    return mask, float(speech_frames.mean())


def estimate_snr(audio: np.ndarray, sample_rate: int, frame_ms: int = 30) -> float:
    """Rough whole-file SNR in dB from 30 ms frame energies.

    Noise floor is the 10th-percentile frame RMS, so it still works when nobody
    pauses; speech is the frames above the geometric midpoint between that floor
    and the 95th percentile, so the split follows the recording rather than a
    fixed level. A gate signal, not a measurement: continuous speech reads lower
    than it is, and a stationary signal reads about 0 dB.
    """
    frame_length = max(1, int(sample_rate * frame_ms / 1000))
    frame_count = audio.size // frame_length
    if frame_count < 2:
        return 60.0
    frames = audio[: frame_count * frame_length].reshape(frame_count, frame_length)
    frame_rms = np.sqrt(np.mean(np.square(frames), axis=1))
    noise_rms = max(float(np.percentile(frame_rms, 10)), 1e-6)
    cut = math.sqrt(noise_rms * float(np.percentile(frame_rms, 95)))
    speech = frame_rms[frame_rms >= cut]
    speech_rms = float(np.sqrt(np.mean(np.square(speech))))
    return round(min(60.0, 20.0 * math.log10(speech_rms / noise_rms)), 2)


def dbfs(rms: float) -> float:
    return float(20.0 * math.log10(max(float(rms), 1e-12)))






def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
