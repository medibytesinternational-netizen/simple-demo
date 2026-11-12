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
    llm_mode: str = os.getenv("LLM_MODE", "auto").lower()
    medibytes_api_key: str = os.getenv("MEDIBYTES_API_KEY", "")
    medibytes_base_url: str = os.getenv("MEDIBYTES_BASE_URL", "https://product-production-b091.up.railway.app")
    medibytes_company_id: int = int(os.getenv("MEDIBYTES_COMPANY_ID", "1"))
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
        if self.llm_mode == "live":
            return bool(self.openai_api_key)
        return bool(self.openai_api_key)

    @property
    def effective_llm_mode(self) -> str:
        return "live" if self.live_llm else "cached"


settings = Settings()
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
