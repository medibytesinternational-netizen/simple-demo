"""Pipeline vocabulary: the seven stages, their states, and one clip's result.

The chart rows themselves stay plain dicts in the JSON shapes described by
`schemas/entities.schema.json` and `schemas/discharge.schema.json`; those
shapes are the contract with the API and the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StageName(str, Enum):
    PREPROCESS = "preprocess"
    MEDASR = "medasr"
    SECOND_PASS = "second_pass"
    EXTRACT = "extract"
    LLM_REVIEW = "llm_review"
    VERIFY = "verify"
    DISCHARGE = "discharge"


STAGE_LABELS = {
    StageName.PREPROCESS: "Preprocess",
    StageName.MEDASR: "MedASR",
    StageName.SECOND_PASS: "Second pass",
    StageName.EXTRACT: "Fuzzy match",
    StageName.LLM_REVIEW: "gpt-4.1 review",
    StageName.VERIFY: "Verify",
    StageName.DISCHARGE: "Discharge note",
}

STAGE_ORDER = tuple(StageName)


class StageState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    DEGRADED = "degraded"  # finished, but an LLM call or the second pass did not run
    FAILED = "failed"


@dataclass(frozen=True)
class StageEvent:
    stage: StageName
    state: StageState
    seconds: float | None = None
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"name": self.stage.value, "label": STAGE_LABELS[self.stage],
                "state": self.state.value, "seconds": self.seconds, "detail": self.detail}


@dataclass
class ClipResult:
    """Everything one run produced. Each field is also written to `out_dir`."""

    clean_meta: dict[str, Any]
    transcript: dict[str, Any]
    entities: dict[str, Any]   # includes "verify" and "discharge", as entities.json
    stages: list[StageEvent] = field(default_factory=list)

    @property
    def verify(self) -> dict[str, Any]:
        return self.entities["verify"]

    @property
    def discharge(self) -> dict[str, Any]:
        return self.entities["discharge"]

    def stage_json(self) -> list[dict[str, Any]]:
        return [e.to_json() for e in self.stages]
