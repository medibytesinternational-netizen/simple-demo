r"""Offline contract check for the F1-F16 demo module registry.

Run from ``backend/``:

    .\.venv\Scripts\python contract_check.py

It imports the FastAPI app, so it does not need a server or database. It
checks that every module in ``app.modules`` has a surface, a human gate and
real routes, and that the LLM schema registry still covers the drafting
modules.
"""

from __future__ import annotations

import sys

from app.main import app
from app.modules import MODULES
from app.schemas import FEATURE_MODELS
from app.services.drafts import _clear_generated_authorship

EXPECTED_IDS = [f"F{number}" for number in range(1, 17)]
EXPECTED_LLM_IDS = {
    "F1",
    "F2",
    "F3",
    "F4",
    "F5",
    "F6",
    "F7",
    "F9",
    "F10",
    "F11",
    "F12",
    "F13",
}


def main() -> int:
    errors: list[str] = []
    paths = set(app.openapi()["paths"])

    ids = [module["id"] for module in MODULES]
    if ids != EXPECTED_IDS:
        errors.append(f"module ids/order must be F1..F16, got {ids}")

    for module in MODULES:
        label = module.get("id", "<missing id>")
        for field in ("name", "workspace", "capability", "llm", "human_gate"):
            if not str(module.get(field, "")).strip():
                errors.append(f"{label}: missing {field}")
        endpoints = module.get("endpoints") or []
        if not endpoints:
            errors.append(f"{label}: no endpoints registered")
        for path in endpoints:
            if path not in paths:
                errors.append(f"{label}: endpoint not mounted: {path}")

    if set(FEATURE_MODELS) != EXPECTED_LLM_IDS:
        errors.append(
            "LLM schema registry drift: "
            f"missing={sorted(EXPECTED_LLM_IDS - set(FEATURE_MODELS))} "
            f"extra={sorted(set(FEATURE_MODELS) - EXPECTED_LLM_IDS)}"
        )

    for required in ("/api/modules", "/api/meta", "/api/hospital/dashboard"):
        if required not in paths:
            errors.append(f"required route not mounted: {required}")

    generated_claim = {"claim": {"text": "model text", "human_authored": True}}
    _clear_generated_authorship(generated_claim)
    if generated_claim["claim"]["human_authored"] is not False:
        errors.append("generated content can incorrectly claim human authorship")

    if errors:
        print("CONTRACT CHECK FAILED")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(f"CONTRACT CHECK PASSED: {len(MODULES)} modules, {len(paths)} mounted paths")
    for module in MODULES:
        print(f"  {module['id']}  {module['name']}  [{module['workspace'].replace('→', '>')}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
