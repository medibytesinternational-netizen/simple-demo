from pathlib import Path

PROMPT_FILES = {
    "F1": "f01_consult_note.md",
    "F2": "f02_admission_note.md",
    "F3": "f03_round.md",
    "F4": "f04_progress.md",
    "F5": "f05_alert.md",
    "F6": "f06_recon.md",
    "F7": "f07_icu.md",
    "F9": "f09_discharge.md",
    "F10": "f10_investigation.md",
    "F11": "f11_referral.md",
    "F12": "f12_claim.md",
    "F13": "f13_leakage.md",
}
VERSIONS = {feature: "v1" for feature in PROMPT_FILES}
VERSIONS.update(
    {
        "F1": "v2",
        "F2": "v2",
        "F3": "v3",
        "F7": "v2",
        "F9": "v2",
        "F10": "v2",
        "F11": "v2",
        "F12": "v3",
    }
)
BASE_DIR = Path(__file__).resolve().parent


def load_prompt(feature: str) -> str:
    filename = PROMPT_FILES.get(feature)
    if not filename:
        raise ValueError(f"No prompt configured for {feature}")
    return (BASE_DIR / filename).read_text(encoding="utf-8")
