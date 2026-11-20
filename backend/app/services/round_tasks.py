"""Who does a ward-round task, what kind it is, and when it is due.

Used by the offline F3 generator and to fill in anything a live model leaves out.
The senior doctor reviews every value before the tasks are assigned.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

ROLES = ("senior_doctor", "junior_doctor", "nurse")

_TO_NURSE = re.compile(r"\b(nurse|sister|staff nurse|anita)\b", re.I)
_TO_JUNIOR = re.compile(r"\b(junior|resident|house ?officer|registrar|dr\.? ?kiran|kiran)\b", re.I)
_NURSE_WORK = re.compile(
    r"\b(vitals?|obs|observations?|monitor\w*|chart\w*|record\w*|input.?output|i/?o|intake|"
    r"give|administer\w*|nebuli[sz]\w*|dressing|wound care|position\w*|turn\w*|"
    r"sample|swab|catheter care|grbs|blood sugar|temperature|spo2|oxygen saturation|"
    r"ambulat\w*|mobili[sz]\w*|bed ?bath|hourly)\b",
    re.I,
)
_CATEGORY = [
    ("ct", re.compile(r"\bct\b|computed tomograph", re.I)),
    ("mri", re.compile(r"\bmri\b|magnetic resonance", re.I)),
    ("xray", re.compile(r"x-?ray|radiograph|\bcxr\b", re.I)),
    ("ultrasound", re.compile(r"ultrasound|\busg\b|sonograph|doppler|echo\b", re.I)),
    ("ecg", re.compile(r"\becg\b|\bekg\b|electrocardiogra", re.I)),
    ("lab", re.compile(r"\b(blood|creatinine|urea|potassium|sodium|electrolytes?|cbc|lft|rft|inr|"
                       r"culture|hba1c|crp|lactate|troponin|sample|glucose|grbs)\b", re.I)),
]
_NUMBER = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "eight": 8, "twelve": 12,
           "an": 1, "a": 1}
_IN_HOURS = re.compile(r"\b(?:in|within|after)\s+(\d+|one|two|three|four|five|six|eight|twelve|an|a)\s*(?:hours?|hrs?|h)\b", re.I)
_IN_MINUTES = re.compile(r"\b(?:in|within)\s+(\d+)\s*(?:minutes?|mins?)\b", re.I)
_BY_CLOCK = re.compile(r"\b(?:by|before|at)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)", re.I)
_NOW = re.compile(r"\b(stat|immediately|right away|right now|now)\b", re.I)
_TONIGHT = re.compile(r"\b(tonight|this evening|by evening)\b", re.I)
_TOMORROW = re.compile(r"\b(tomorrow|next morning|in the morning)\b", re.I)


def assignee_role(text: str) -> str:
    """Junior doctor or nurse. A role named in the sentence wins; otherwise the kind of work decides."""
    if _TO_NURSE.search(text):
        return "nurse"
    if _TO_JUNIOR.search(text):
        return "junior_doctor"
    return "nurse" if _NURSE_WORK.search(text) else "junior_doctor"


def category(text: str) -> str:
    return next((name for name, pattern in _CATEGORY if pattern.search(text)), "general")


def due_in_hours(text: str, urgent: bool, now: datetime | None = None) -> int:
    """A time said on the round, else 8 h for urgent work and 24 h for routine work."""
    now = now or datetime.now()
    if _NOW.search(text):
        return 1
    if m := _IN_MINUTES.search(text):
        return max(1, round(int(m.group(1)) / 60))
    if m := _IN_HOURS.search(text):
        raw = m.group(1).lower()
        return max(1, int(raw) if raw.isdigit() else _NUMBER.get(raw, 1))
    if m := _BY_CLOCK.search(text):
        hour = int(m.group(1)) % 12 + (12 if m.group(3).lower().startswith("p") else 0)
        target = now.replace(hour=hour, minute=int(m.group(2) or 0), second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return max(1, round((target - now).total_seconds() / 3600))
    if _TONIGHT.search(text):
        target = now.replace(hour=21, minute=0, second=0, microsecond=0)
        return max(1, round((target - now).total_seconds() / 3600)) if target > now else 4
    if _TOMORROW.search(text):
        return 24
    return 8 if urgent else 24


def fill(task: dict[str, Any]) -> dict[str, Any]:
    """Complete a proposed task with a role and category when a model left them out or got them wrong."""
    text = f"{task.get('title', '')} {task.get('detail', '')}"
    if task.get("assignee_role") not in ROLES:
        task["assignee_role"] = assignee_role(text)
    if not task.get("category") or task.get("category") == "general":
        task["category"] = category(text)
    return task
