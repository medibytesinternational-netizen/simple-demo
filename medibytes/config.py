"""The one pipeline this package runs, and every number it was measured with.

C1 from the Phone40 evaluation (11 Oct 2026): MedASR first pass, faster-whisper
small-int8 second pass, fuzzy drug matcher, gpt-4.1 term validation and context
repair, then a gpt-4.1 six-section discharge note gated against the transcript.
It scored 92.6% of chart facts (212/229). Change a value here only together with a
re-score (`python -m evaluation.phone40.score`); the modules bind these values and
explain each one where it is used.

`Settings` is the deployment side: secrets, paths and ports, read from the
environment. Nothing in `Settings` changes what the pipeline computes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AudioConfig:
    target_sample_rate: int = 16000
    max_bytes: int = 100 * 1024 * 1024
    max_seconds: int = 30 * 60
    min_seconds: float = 0.6
    target_rms: float = 0.1          # about -20 dBFS
    peak_ceiling: float = 0.98
    silence_peak: float = 0.005      # below this the file is digital silence
    vad_frame_ms: int = 30
    vad_threshold: float = 0.02
    min_speech_ratio: float = 0.05   # >95% silent is rejected


@dataclass(frozen=True)
class AsrConfig:
    medasr_model_id: str = "google/medasr"
    medasr_chunk_s: int = 20
    medasr_stride_s: int = 2
    # The second pass is faster-whisper "small" in int8 on CPU, greedy decoding.
    second_pass_label: str = "small-int8"
    whisper_size: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_decode: tuple[tuple[str, object], ...] = (
        ("beam_size", 1), ("temperature", 0.0),
        ("no_speech_threshold", 0.6), ("compression_ratio_threshold", 2.4),
        ("word_timestamps", True),
    )


@dataclass(frozen=True)
class MatcherConfig:
    # Dosed path against the curated mini list.
    dosed_floor_long: float = 0.55   # token of 8+ letters
    dosed_floor_short: float = 0.60
    dosed_long_len: int = 8
    mini_limit: int = 5
    mini_band: float = 0.08
    reference_margin: float = 0.08
    shortlist_limit: int = 6
    # Doseless mentions against the national reference.
    doseless_floor: float = 0.84
    # National reference fuzzy search.
    reference_min_len: int = 6
    reference_floor: float = 0.78
    reference_band: float = 0.06
    reference_limit: int = 5
    dose_tolerance: float = 20.0


@dataclass(frozen=True)
class LlmConfig:
    model: str = "gpt-4.1"
    base_url: str = "https://api.openai.com/v1"
    prompt_version: str = "p0"
    # Term validation.
    validate_min_confidence: float = 0.85
    validate_tie_band: float = 0.03
    validate_timeout_s: float = 45
    validate_max_tokens: int = 256
    # Context repair.
    repair_floor: float = 0.78
    repair_band: float = 0.10
    repair_limit: int = 4
    repair_min_token_len: int = 6
    repair_min_confidence: float = 0.85
    repair_max_calls: int = 40
    repair_timeout_s: float = 30
    repair_max_tokens: int = 200
    # Discharge note.
    discharge_timeout_s: float = 300
    discharge_max_tokens: int = 4096  # 1024 truncated real notes mid-JSON
    discharge_max_facts: int = 60
    discharge_transcript_chars: int = 6000


@dataclass(frozen=True)
class PipelineConfig:
    name: str = "MedASR → small-int8 second pass → fuzzy matcher → gpt-4.1"
    audio: AudioConfig = field(default_factory=AudioConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    matcher: MatcherConfig = field(default_factory=MatcherConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)


C1 = PipelineConfig()

PACKAGE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PACKAGE_DIR / "reference" / "assets"
SCHEMAS_DIR = PACKAGE_DIR / "schemas"


@dataclass(frozen=True)
class Settings:
    """Deployment settings from the environment (and an optional `.env`)."""

    openai_api_key: str = ""
    runs_dir: Path = Path("runs")
    host: str = "127.0.0.1"
    port: int = 8000
    max_upload_bytes: int = 64 * 1024 * 1024
    llm_trace: Path | None = None  # .jsonl of every gpt-4.1 prompt and reply
    web_dist: Path = PACKAGE_DIR.parent / "frontend" / "dist"
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    # HIMS (hospital) integration. api_keys guard /api/v1 only; the UI's /api/jobs stays open.
    api_keys: tuple[str, ...] = ()
    hims_url: str = ""        # the full receive URL; deliveries wait while it is empty
    hims_token: str = ""      # their Bearer token, sent only to hims_url
    hims_backoff_s: tuple[float, ...] = (10, 60, 300, 900, 1800)  # one retry per entry
    hims_poll_s: float = 3.0

    @classmethod
    def from_env(cls, env_file: Path | None = Path(".env")) -> Settings:
        values = dict(_read_env_file(env_file)) if env_file else {}
        values.update(os.environ)
        # The local `.env` parser is intentionally small and does not load dotenv
        # process-wide. Surface Hugging Face settings to its libraries as well as
        # the MediBytes Settings object.
        for name in ("HF_TOKEN", "HF_HOME"):
            if value := values.get(name, "").strip():
                os.environ[name] = value
        trace = values.get("MEDIBYTES_LLM_TRACE")
        cors_value = values.get("MEDIBYTES_CORS_ORIGINS")
        cors_origins = (
            tuple(origin.strip() for origin in cors_value.split(",") if origin.strip())
            if cors_value is not None
            else ("http://localhost:5173", "http://127.0.0.1:5173")
        )
        return cls(
            openai_api_key=values.get("OPENAI_API_KEY", "").strip(),
            runs_dir=Path(values.get("MEDIBYTES_RUNS", "runs")),
            host=values.get("MEDIBYTES_HOST", "127.0.0.1"),
            port=int(values.get("MEDIBYTES_PORT", "8000")),
            max_upload_bytes=int(values.get("MEDIBYTES_MAX_UPLOAD_BYTES", str(64 * 1024 * 1024))),
            llm_trace=Path(trace) if trace else None,
            cors_origins=cors_origins,
            api_keys=tuple(k.strip() for k in values.get("MEDIBYTES_API_KEYS", "").split(",")
                           if k.strip()),
            hims_url=values.get("MEDIBYTES_HIMS_URL", "").strip(),
            hims_token=values.get("MEDIBYTES_HIMS_TOKEN", "").strip(),
        )


def _read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; blank lines and # comments ignored. Missing file is empty."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out
