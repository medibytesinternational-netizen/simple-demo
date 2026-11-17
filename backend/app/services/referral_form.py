"""The hospital referral form, part one (filled by the referring doctor).

  Header: Name, Sex, Ward, HID number                       <- the record
  Referral type: Immediate (1 h), Urgent (4 h), Routine (24 h) <- the dictation
  Unit chief requested of (doctor's name), Department       <- the dictation
  Salient details of the patient or reason for referral     <- the dictation, then the patient's
                                                               earlier record (problems, signed
                                                               assessments, abnormal results)
  Doctor's name and signature, Date and time                <- stamped when the doctor approves
"""

from __future__ import annotations

import re
from datetime import datetime
from html import escape as esc
from typing import Any

from ..models import Encounter, Patient

REFERRAL_FORMAT = "referral_v2"
REFERRAL_DOC_TYPE = "referral_form"

TYPES = {
    "immediate": "Immediate (within one hour)",
    "urgent": "Urgent (within four hours)",
    "routine": "Routine (within twenty-four hours)",
}
# Referral.urgency values the hospital link already understands.
URGENCY = {"immediate": "emergency", "urgent": "urgent", "routine": "routine"}

HEADER_FIELDS = [("name", "Name"), ("sex", "Sex"), ("ward", "Ward"), ("hid", "HID number")]


def referral_type(text: str | None) -> str | None:
    """Immediate / Urgent / Routine from what was said, or None when it cannot be told."""
    said = (text or "").lower()
    if re.search(r"immediate|emergency|stat\b|right now|within (an|one) hour", said):
        return "immediate"
    if re.search(r"urgent|within (four|4) hours", said):
        return "urgent"
    if re.search(r"routine|within (24|twenty[- ]four) hours|when (possible|convenient)", said):
        return "routine"
    return None


def header(patient: Patient, encounter: Encounter | None) -> dict[str, str]:
    ward = " / ".join(x for x in ((encounter.ward if encounter else "") or "", f"Bed {encounter.bed}" if encounter and encounter.bed else "") if x)
    return {"name": patient.name or "", "sex": patient.sex or "", "ward": ward, "hid": patient.mrn or ""}


def _text(value: Any) -> str:
    return str(value.get("text") or "").strip() if isinstance(value, dict) else str(value or "").strip()


def missing(content: dict[str, Any]) -> list[str]:
    out = []
    if content.get("referral_type") not in TYPES:
        out.append("Referral type")
    if not _text(content.get("unit_chief")):
        out.append("Unit chief requested of")
    if not _text(content.get("department")):
        out.append("Department")
    if not [c for c in content.get("salient_details") or [] if _text(c)]:
        out.append("Salient details or reason for referral")
    return out


def _when(value: str | datetime | None) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d %b %Y, %H:%M") if value else ""


def render_html(content: dict[str, Any]) -> str:
    head = content.get("header") or {}
    signed = content.get("signed_by") or {}
    record = "".join(
        f"<div class='kv'><span>{esc(label)}</span><b>{esc(str(head.get(k) or '-'))}</b></div>" for k, label in HEADER_FIELDS
    )
    kind = content.get("referral_type")
    types = "".join(
        f"<span class='opt{' on' if key == kind else ''}'>{'&#9746;' if key == kind else '&#9744;'} {esc(label)}</span>"
        for key, label in TYPES.items()
    )
    details = [c for c in content.get("salient_details") or [] if _text(c)]
    details_html = "<ul>" + "".join(
        f"<li>{esc(_text(c))}{' <span class=src>(from the record)</span>' if isinstance(c, dict) and c.get('origin') == 'record' else ''}</li>"
        for c in details
    ) + "</ul>" if details else "<p class='muted'>Not documented</p>"

    def row(label: str, body: str) -> str:
        return f"<tr><th>{esc(label)}</th><td>{body}</td></tr>"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Referral - {esc(head.get('name') or 'Patient')}</title>
<style>
@page {{ size: A4; margin: 16mm; }}
body {{ font-family: "Segoe UI", Tahoma, Arial, sans-serif; color: #10213d; margin: 32px auto; max-width: 780px; padding: 0 16px; font-size: 13.5px; line-height: 1.5; background: #fff; }}
header {{ border-bottom: 2px solid #0b3d91; padding-bottom: 10px; margin-bottom: 14px; }}
.hosp {{ font-size: 12px; font-weight: 700; letter-spacing: .5px; color: #0b3d91; text-transform: uppercase; }}
h1 {{ font-size: 20px; margin: 4px 0 8px; }} h2 {{ font-size: 13px; text-transform: uppercase; color: #0b3d91; margin: 16px 0 6px; }}
.record {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid #c8d9f0; }}
.kv {{ display: flex; gap: 8px; padding: 5px 8px; border-bottom: 1px solid #e3ecf8; font-size: 12.5px; }}
.kv span {{ color: #4a5f80; min-width: 100px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ text-align: left; vertical-align: top; padding: 7px 9px; border: 1px solid #c8d9f0; }}
th {{ background: #eef4fc; width: 230px; font-weight: 600; }}
.opt {{ display: block; color: #4a5f80; }} .opt.on {{ color: #10213d; font-weight: 700; }}
ul {{ margin: 0; padding-left: 18px; }} .muted, .src {{ color: #4a5f80; }}
.print {{ float: right; font: inherit; font-size: 12px; padding: 4px 12px; border: 1px solid #0b3d91; background: #fff; color: #0b3d91; cursor: pointer; }}
@media print {{ .print {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<header><button class="print" onclick="window.print()">Print</button>
<div class="hosp">MediBytes Hospital &middot; Referral</div><h1>Referral form</h1></header>
<div class="record">{record}</div>
<h2>Part one: to be filled by the referring doctor</h2>
<table>
{row("Referral type", types)}
{row("Unit chief requested of (doctor's name)", esc(_text(content.get("unit_chief")) or "-"))}
{row("Department", esc(_text(content.get("department")) or "-"))}
{row("Salient details of the patient or reason for referral", details_html)}
{row("Doctor's name and signature", esc(signed.get("name") or "-") + (f"<br><span class='muted'>{esc(signed.get('role') or '')}</span>" if signed.get("role") else ""))}
{row("Date and time", esc(_when(content.get("signed_at")) or "-"))}
</table>
</body></html>"""
