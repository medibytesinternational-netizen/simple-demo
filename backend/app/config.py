import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(value: str | None) -> bool:
    return (value or "").lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    hf_token: str = os.getenv("HF_TOKEN", "")
    hf_model: str = os.getenv("HF_MODEL", "deepseek-ai/DeepSeek-V4.1-Flash:fastest")
    hf_asr_model: str = os.getenv("HF_ASR_MODEL", "openai/whisper-large-v3")
    llm_provider: str = os.getenv("LLM_PROVIDER", "auto").lower()
    llm_mode: str = os.getenv("LLM_MODE", "auto").lower()
    medibytes_runs_dir: Path = Path(os.getenv("MEDIBYTES_RUNS_DIR") or BASE_DIR / "runs")
    # "real": every record is stamped with the actual current time (local wall clock).
    # "demo": the fixed scenario clock starting at demo_now (tests use this so they repeat exactly).
    clock_mode: str = os.getenv("MEDIBYTES_CLOCK", "real").lower()
    demo_now: datetime = datetime.fromisoformat(
        os.getenv("DEMO_NOW", "2026-10-20T09:00:00")
    )
    database_url: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{(BASE_DIR / 'medibytes.db').as_posix()}"
    )
    uploads_dir: Path = Path(os.getenv("UPLOADS_DIR", BASE_DIR / "uploads"))
    demo_user: str = "Dr. Meera Shah"
    demo_role: str = "Attending physician"

    @property
    def live_llm(self) -> bool:
        if self.llm_mode == "cached":
            return False
        if self.active_llm_provider == "huggingface":
            return bool(self.hf_token)
        return bool(self.openai_api_key)

    @property
    def active_llm_provider(self) -> str:
        if self.llm_provider in {"openai", "huggingface"}:
            return self.llm_provider
        return "huggingface" if self.hf_token and not self.openai_api_key else "openai"

    @property
    def active_model(self) -> str:
        return self.hf_model if self.active_llm_provider == "huggingface" else self.openai_model

    @property
    def effective_llm_mode(self) -> str:
        return "live" if self.live_llm else "cached"


settings = Settings()
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
