"""Stage 1 - any supported audio file in, a clean 16 kHz mono PCM16 WAV out.

    decode (WAV directly, anything else through ffmpeg) -> mono -> anti-aliased
    resample to 16 kHz -> reject digital silence -> RMS level-normalise (0.1 RMS,
    0.98 peak ceiling) -> reject >95% silent audio -> write PCM16 -> measure SNR

No denoiser: the Phone40 recordings measured 9-34 dB SNR and no SNR-gated
denoising threshold improved facts over none, so the signal is only standardised.
The output is deterministic, so the same input file always yields the same bytes.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ..config import C1
from ..errors import AudioRejected
from .audio import check_audio, dbfs, decode_mono_16k, estimate_snr, file_sha256, rms_vad, save_pcm16_wav

STEPS = ("decode", "downmix-mono", "resample-16k", "silence-check", "rms-normalise",
         "speech-ratio-check", "pcm16-write", "snr-estimate")


class Preprocessor:
    """The Stage 1 implementation of `ports.AudioPreprocessor`."""

    def clean(self, src: Path, dst: Path) -> dict:
        started = time.perf_counter()
        cfg = C1.audio
        src, dst = Path(src), Path(dst)

        input_info = check_audio(src)
        input_hash = file_sha256(src)
        audio, rate = decode_mono_16k(src)
        if audio.ndim != 1 or audio.size == 0:
            raise AudioRejected("422 NO_AUDIO: decoder returned empty or non-mono audio")
        if not np.isfinite(audio).all():
            raise AudioRejected("422 DECODE_FAIL: decoder returned non-finite samples")
        raw_peak = float(np.max(np.abs(audio)))
        raw_rms = float(np.sqrt(np.mean(np.square(audio))))
        if raw_peak < cfg.silence_peak or raw_rms <= 0.0:
            raise AudioRejected("422 NO_AUDIO: digital silence (peak<0.005)")

        # Level-normalise to the target RMS, then pull the peak under the ceiling.
        rms_gain = cfg.target_rms / raw_rms
        rms_scaled_peak = raw_peak * rms_gain
        peak_scale = min(1.0, cfg.peak_ceiling / rms_scaled_peak) if rms_scaled_peak > 0 else 1.0
        total_gain = rms_gain * peak_scale
        prepared = np.asarray(audio * total_gain, dtype=np.float32)
        prepared_peak = float(np.max(np.abs(prepared)))
        prepared_rms = float(np.sqrt(np.mean(np.square(prepared))))
        if not np.isfinite(prepared).all() or prepared.size == 0:
            raise AudioRejected("422 DECODE_FAIL: preprocessing produced invalid audio")
        if prepared_peak < cfg.silence_peak:
            raise AudioRejected("422 NO_AUDIO: digital silence after preprocessing")

        _, vad_ratio = rms_vad(prepared, rate, frame_ms=cfg.vad_frame_ms,
                               threshold=cfg.vad_threshold)
        if vad_ratio < cfg.min_speech_ratio or prepared.size < int(rate * cfg.min_seconds):
            raise AudioRejected("422 NO_AUDIO: >95% silent or <0.6s speech")

        save_pcm16_wav(dst, prepared, rate)
        duration = prepared.size / float(rate)
        return {
            "input": input_info,
            "input_sha256": input_hash,
            "output_sha256": file_sha256(dst),
            "sample_rate": rate,
            "channels": 1,
            "sample_count": int(prepared.size),
            "duration_s": round(duration, 6),
            "vad_ratio": round(vad_ratio, 3),
            "snr_db": estimate_snr(prepared, rate),
            "rms_dbfs_before": round(dbfs(raw_rms), 3),
            "rms_dbfs_after": round(dbfs(prepared_rms), 3),
            "rms_gain_linear": round(float(rms_gain), 9),
            "peak_scale": round(float(peak_scale), 9),
            "total_gain_linear": round(float(total_gain), 9),
            "peak_before": round(raw_peak, 9),
            "peak_after": round(prepared_peak, 9),
            "clipping_count": int(np.count_nonzero(np.abs(prepared) >= 1.0)),
            "denoiser": "none",
            "steps": list(STEPS),
            "processing_time_s": round(time.perf_counter() - started, 6),
        }
