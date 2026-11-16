from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import settings

# The demo runs on a fixed clinical clock, but actions still need to advance
# in a natural order. Anchor the demo clock at the configured demo time and
# let it move forward with real elapsed time since the process started.
_real_start = datetime.now(timezone.utc).replace(tzinfo=None)
_demo_start = settings.demo_now


def real_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now() -> datetime:
    """The time a record is stamped with: the real current time, or the demo scenario clock."""
    if settings.clock_mode != "demo":
        return datetime.now()
    return _demo_start + (real_utcnow() - _real_start)


def resume_after(latest: datetime | None) -> None:
    """Carry on after the latest recorded time instead of starting again from the demo time.

    Without this, every server restart sends the clock back, and anything recorded afterwards
    sorts before what was recorded earlier (timeline, drafts, audit).
    """
    global _real_start
    if latest and latest >= now():
        _real_start = real_utcnow() - (latest - _demo_start) - timedelta(seconds=1)


def reset() -> None:
    global _real_start
    _real_start = real_utcnow()
