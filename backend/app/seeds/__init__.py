"""Seed data added by feature work. Drop a module here; it is loaded automatically.

A hook receives the session and the reset mode ("rehearsal" or "start") and runs after the base seed.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable

from sqlalchemy.orm import Session

HOOKS: list[Callable[[Session, str], None]] = []


def seed_hook(fn):
    HOOKS.append(fn)
    return fn


def run_hooks(db: Session, mode: str) -> None:
    for hook in HOOKS:
        hook(db, mode)


for _info in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_info.name}")
