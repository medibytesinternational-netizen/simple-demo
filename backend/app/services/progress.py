"""Daily progress notes: one table for doctors, one for nurses.

Each entry is dictated, written by the MediBytes pipeline and signed straight away by the person who
recorded it; it is a timeline event and a row in its table. Nothing supersedes: every day's entry
stays. "Generate report" prints a table in the hospital format:

  Header:  Name, Sex, Age, Ward, Bed, UHID number
  Columns: Date and time, Notes, Name and sign
"""

from __future__ import annotations

from datetime import datetime
from html import escape as esc
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Encounter, Patient, TimelineEvent
from .identity import ROLE_LABELS, acting_user

PROGRESS_FORMAT = "progress_v2"
ROLES = ("doctor", "nurse")
EVENT_TYPE = {"doctor": "progress_note", "nurse": "nurse_progress_note"}
TITLE = {"doctor": "Doctor's progress note", "nurse": "Nurse's progress note"}
TABLE_TITLE = {"doctor": "Doctor's progress notes", "nurse": "Nurse's progress notes", None: "Progress notes"}
REPORT_TYPE = "progress_report"

# Who may write which table (Admin may write both until the role lists are set).
WRITERS = {
    "doctor": {"doctor", "senior_doctor", "junior_doctor"},
    "nurse": {"doctor", "nurse"},
}

HEADER_FIELDS: list[tuple[str, str]] = [
    ("name", "Name"), ("sex", "Sex"), ("age", "Age"), ("ward", "Ward"), ("bed", "Bed"), ("uhid", "UHID number"),
]


def default_role() -> str:
    return "nurse" if acting_user().role == "nurse" else "doctor"


def may_write(role: str) -> bool:
    return role in WRITERS and acting_user().role in WRITERS[role]


def header(patient: Patient, encounter: Encounter | None) -> dict[str, str]:
    return {
        "name": patient.name or "",
        "sex": patient.sex or "",
        "age": f"{patient.age} years" if patient.age is not None else "",
        "ward": (encounter.ward if encounter else "") or "",
        "bed": (encounter.bed if encounter else "") or "",
        "uhid": patient.mrn or "",
    }


def signature() -> dict[str, str]:
    user = acting_user()
    return {"name": user.name, "role": ROLE_LABELS.get(user.role, user.role)}


def notes_text(payload: dict[str, Any]) -> str:
    items = payload.get("notes") or []
    texts = [str(i.get("text") if isinstance(i, dict) else i or "").strip() for i in items]
    return "\n".join(t for t in texts if t)


def rows(db: Session, patient_id: str, role: str | None = None) -> list[dict[str, Any]]:
    """Signed entries, oldest first: one role's, or everyone's (doctors and nurses together)."""
    types = [EVENT_TYPE[role]] if role else list(EVENT_TYPE.values())
    events = db.scalars(
        select(TimelineEvent)
        .where(
            TimelineEvent.patient_id == patient_id,
            TimelineEvent.type.in_(types),
            TimelineEvent.status == "approved",
        )
        .order_by(TimelineEvent.occurred_at.asc())
    ).all()
    out = []
    for event in events:
        payload = event.payload or {}
        if payload.get("format") != PROGRESS_FORMAT:
            continue
        signed = payload.get("signed_by") or {}
        out.append({
            "event_id": event.id,
            "time": event.occurred_at.isoformat() if event.occurred_at else "",
            "notes": notes_text(payload),
            "signed_by": signed.get("name") or event.approved_by or "",
            "signed_role": signed.get("role") or "",
            # Scans and reports this note asked for; each raised an investigation request.
            "orders": [
                {"study": o.get("study"), "request_type": o.get("request_type"),
                 "request_id": o.get("request_id"), "priority": o.get("priority")}
                for o in payload.get("orders") or []
            ],
        })
    return out


def _when(value: str | datetime) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d %b %Y, %H:%M")


def render_report_html(head: dict[str, str], role: str | None, table: list[dict[str, Any]], made_by: str, made_at: datetime) -> str:
    record = "".join(
        f"<div class='kv'><span>{esc(label)}</span><b>{esc(str(head.get(key) or '-'))}</b></div>"
        for key, label in HEADER_FIELDS
    )
    body = "".join(
        "<tr>"
        f"<td class='t'>{esc(_when(r['time']))}</td>"
        f"<td>{'<br>'.join(esc(line) for line in r['notes'].splitlines()) or '-'}</td>"
        f"<td class='s'>{esc(r['signed_by'])}<br><span class='muted'>{esc(r['signed_role'])}</span></td>"
        "</tr>"
        for r in table
    ) or "<tr><td colspan='3' class='muted'>No entries yet.</td></tr>"
    title = TABLE_TITLE[role]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} - {esc(head.get('name') or 'Patient')}</title>
<style>
@page {{ size: A4; margin: 16mm; }}
body {{ font-family: "Segoe UI", Tahoma, Arial, sans-serif; color: #10213d; margin: 32px auto; max-width: 820px; padding: 0 16px; font-size: 13.5px; line-height: 1.5; background: #fff; }}
header {{ border-bottom: 2px solid #0b3d91; padding-bottom: 10px; margin-bottom: 14px; }}
.hosp {{ font-size: 12px; font-weight: 700; letter-spacing: .5px; color: #0b3d91; text-transform: uppercase; }}
h1 {{ font-size: 20px; margin: 4px 0 8px; }}
.record {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid #c8d9f0; margin-bottom: 14px; }}
.kv {{ display: flex; gap: 8px; padding: 5px 8px; border-bottom: 1px solid #e3ecf8; font-size: 12.5px; }}
.kv span {{ color: #4a5f80; min-width: 90px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ text-align: left; vertical-align: top; padding: 6px 8px; border: 1px solid #c8d9f0; }}
th {{ background: #eef4fc; }}
td.t {{ white-space: nowrap; width: 130px; }} td.s {{ width: 170px; }}
tr {{ break-inside: avoid; }}
.muted {{ color: #4a5f80; font-size: 12px; }}
footer {{ margin-top: 24px; padding-top: 10px; border-top: 1px solid #c8d9f0; font-size: 12px; color: #4a5f80; }}
.print {{ float: right; font: inherit; font-size: 12px; padding: 4px 12px; border: 1px solid #0b3d91; background: #fff; color: #0b3d91; cursor: pointer; }}
@media print {{ .print {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<header><button class="print" onclick="window.print()">Print</button>
<div class="hosp">MediBytes Hospital &middot; Progress notes</div><h1>{esc(title)}</h1></header>
<div class="record">{record}</div>
<table><thead><tr><th>Date and time</th><th>Notes</th><th>Name and sign</th></tr></thead><tbody>{body}</tbody></table>
<footer>Report generated by {esc(made_by)} on {esc(_when(made_at))}. Each entry was dictated and signed by the person named.</footer>
</body></html>"""
