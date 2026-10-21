from __future__ import annotations

from datetime import datetime, timezone

from .config import settings

# The demo runs on a fixed clinical clock, but actions still need to advance
# in a natural order. Anchor the demo clock at the configured demo time and
# let it move forward with real elapsed time since the process started.
_real_start = datetime.now(timezone.utc).replace(tzinfo=None)
_demo_start = settings.demo_now


def real_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now() -> datetime:
    return _demo_start + (real_utcnow() - _real_start)


def reset() -> None:
    global _real_start
    _real_start = real_utcnow()
