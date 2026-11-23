"""Date parsing for the hospital's local wall clock.

The demo stores clinical timestamps as naive datetimes, using Asia/Kolkata. Incoming
timestamps with an offset are normalized to the same local wall clock before storage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

HOSPITAL_TIMEZONE = ZoneInfo("Asia/Kolkata")


def parse_hospital_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(HOSPITAL_TIMEZONE).replace(tzinfo=None)
    return parsed
