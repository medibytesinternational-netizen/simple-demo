"""Per-feature approval rules.

``approve_draft`` is the single write path. What is special about approving one feature lives in a
module here, registered with a decorator, so features can change independently:

- ``@validator("F4")``       runs before anything is written; raise ValueError to refuse.
- ``@payload_builder("F10")`` may create records and add keys to the event payload.
- ``@after_event("F3")``     runs after the timeline event exists (extra events, links).
- ``@after_commit("F9")``    runs once the draft is marked approved (state changes).

Drop a new module into this package and it is loaded automatically.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ...models import Draft, Encounter, Patient


@dataclass
class ApprovalContext:
    db: Session
    draft: Draft
    payload: dict[str, Any]
    patient: Patient
    encounter: Encounter
    approver: str


VALIDATORS: dict[str, list[Callable[[ApprovalContext], None]]] = defaultdict(list)
PAYLOAD_BUILDERS: dict[str, list[Callable[[ApprovalContext, dict[str, Any]], None]]] = defaultdict(list)
AFTER_EVENT: dict[str, list[Callable[[ApprovalContext, Any], None]]] = defaultdict(list)
AFTER_COMMIT: dict[str, list[Callable[[ApprovalContext, Any], None]]] = defaultdict(list)


def _register(table, feature):
    def decorator(fn):
        table[feature].append(fn)
        return fn

    return decorator


def validator(feature: str):
    return _register(VALIDATORS, feature)


def payload_builder(feature: str):
    return _register(PAYLOAD_BUILDERS, feature)


def after_event(feature: str):
    return _register(AFTER_EVENT, feature)


def after_commit(feature: str):
    return _register(AFTER_COMMIT, feature)


for _info in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_info.name}")
