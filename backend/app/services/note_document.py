"""The signed OPD note as a stored, printable document.

Every signature writes its own file, so a superseded note still opens the version that was signed.
"""

from __future__ import annotations

from datetime import datetime
from html import escape as esc
from typing import Any

from ..models import Encounter, Patient

GENERATED_KIND = "generated"
OPD_NOTE_TYPE = "opd_note"


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or "").strip()
    return str(value or "").strip()


def _section(title: str, body: str) -> str:
    return f"<section><h2>{esc(title)}</h2>{body}</section>" if body else ""


def _para(value: Any) -> str:
    text = _text(value)
    return f"<p>{esc(text)}</p>" if text else ""


def _items(values: list[Any] | None) -> str:
    texts = [_text(v) for v in values or []]
    texts = [t for t in texts if t]
    return "<ul>" + "".join(f"<li>{esc(t)}</li>" for t in texts) + "</ul>" if texts else ""


def _when(value: datetime | None) -> str:
    return value.strftime("%d %b %Y, %H:%M") if value else ""


def _opd_v2_body(content: dict[str, Any]) -> str:
    """The hospital OPD format: record headings as a grid, then every heard heading in order."""
    from ..schemas import OPD_HEARD_SECTIONS
    from .opd import OPD_HEADER_FIELDS

    header = content.get("header") or {}
    record = "".join(
        f"<div class='kv'><span>{esc(label)}</span><b>{esc(str(header.get(key) or '-'))}</b></div>"
        for key, label in OPD_HEADER_FIELDS
    )
    rows = []
    for key, label in OPD_HEARD_SECTIONS:
        value = content.get(key)
        if isinstance(value, list):
            texts = [_text(v) for v in value if _text(v)]
            body = "<ul>" + "".join(f"<li>{esc(t)}</li>" for t in texts) + "</ul>" if texts else ""
        else:
            body = f"<p>{esc(_text(value))}</p>" if _text(value) else ""
        rows.append(
            f"<section><h2>{esc(label)}</h2>{body or '<p class=muted>Not documented</p>'}</section>"
        )
    return f"<div class='record'>{record}</div>" + "".join(rows)


def render_opd_note_html(
    patient: Patient,
    encounter: Encounter,
    content: dict[str, Any],
    signer: str,
    signed_at: datetime,
    drafted_by: str = "MediBytes Analysis",
) -> str:
    exam = content.get("exam") or {}
    exam_html = "".join(
        f"<p><b>{label}:</b> {esc(_text(exam.get(key)))}</p>"
        for key, label in (("general", "General"), ("systemic", "Systemic"))
        if _text(exam.get(key))
    )
    meds = [m for m in content.get("medication_mentions") or [] if isinstance(m, dict) and m.get("drug")]
    meds_html = (
        "<table><thead><tr><th>Medicine</th><th>Dose</th><th>Frequency</th></tr></thead><tbody>"
        + "".join(
            f"<tr><td>{esc(str(m.get('drug', '')))}</td><td>{esc(str(m.get('dose') or '-'))}</td>"
            f"<td>{esc(str(m.get('frequency') or '-'))}</td></tr>"
            for m in meds
        )
        + "</tbody></table>"
        if meds
        else ""
    )
    not_documented = ", ".join(str(x) for x in content.get("not_documented") or [] if x)
    allergies = ", ".join(patient.allergies or []) or "No known drug allergies"
    sections = "".join(
        [
            _section("Chief complaint", _para(content.get("chief_complaint"))),
            _section("History of present illness", _para(content.get("hpi"))),
            _section("Examination", exam_html),
            _section("Assessment", _items(content.get("assessment"))),
            _section("Plan", _items(content.get("plan"))),
            _section("Medicines discussed", meds_html),
            _section("Follow-up", _para(content.get("follow_up"))),
            _section("Not documented", f"<p class='muted'>{esc(not_documented)}</p>" if not_documented else ""),
        ]
    )
    if content.get("format") == "opd_v2":
        sections = _opd_v2_body(content)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>OPD consultation note - {esc(patient.name)}</title>
<style>
@page {{ size: A4; margin: 16mm; }}
body {{ font-family: "Segoe UI", Tahoma, Arial, sans-serif; color: #10213d; margin: 32px auto; max-width: 760px; padding: 0 16px; font-size: 13.5px; line-height: 1.55; background: #fff; }}
header {{ border-bottom: 2px solid #0b3d91; padding-bottom: 10px; margin-bottom: 14px; }}
.hosp {{ font-size: 12px; font-weight: 700; letter-spacing: .5px; color: #0b3d91; text-transform: uppercase; }}
h1 {{ font-size: 20px; margin: 4px 0 8px; }}
.facts {{ display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: 12.5px; }}
.facts b {{ color: #4a5f80; font-weight: 600; margin-right: 4px; }}
.allergy {{ color: #b91c1c; font-weight: 700; }}
h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: .3px; color: #0b3d91; margin: 18px 0 4px; }}
p {{ margin: 4px 0; }} ul {{ margin: 4px 0; padding-left: 20px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ text-align: left; padding: 5px 8px; border-bottom: 1px solid #dbe4f0; }}
th {{ background: #eef4fc; }}
.muted {{ color: #4a5f80; }}
footer {{ margin-top: 28px; padding-top: 10px; border-top: 1px solid #c8d9f0; font-size: 12px; color: #4a5f80; }}
.record {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0; border: 1px solid #c8d9f0; margin-bottom: 6px; }}
.kv {{ display: flex; gap: 8px; padding: 5px 8px; border-bottom: 1px solid #e3ecf8; font-size: 12.5px; }}
.kv span {{ min-width: 190px; color: #4a5f80; }}
@media print {{ .record {{ break-inside: avoid; }} }}
.print {{ float: right; font: inherit; font-size: 12px; padding: 4px 12px; border: 1px solid #0b3d91; background: #fff; color: #0b3d91; cursor: pointer; }}
@media print {{ .print {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<header>
<button class="print" onclick="window.print()">Print</button>
<div class="hosp">MediBytes Hospital &middot; Outpatient department</div>
<h1>OPD consultation note</h1>
<div class="facts">
<span><b>Patient</b>{esc(patient.name)}</span><span><b>MRN</b>{esc(patient.mrn)}</span>
<span><b>Age/Sex</b>{patient.age} / {esc((patient.sex or '')[:1].upper())}</span>
<span><b>Visit</b>{esc(encounter.kind or 'OPD')} &middot; {esc(_when(encounter.admitted_at))}</span>
<span class="allergy"><b>Allergy</b>{esc(allergies)}</span>
</div>
</header>
{sections or "<p class='muted'>No content was recorded in this note.</p>"}
<footer>Signed by {esc(signer)} on {esc(_when(signed_at))}. Drafted by {esc(drafted_by)} from the consultation recording and reviewed by the signing clinician.</footer>
</body></html>"""


ADMISSION_NOTE_TYPE = "admission_note"


def render_admission_note_html(content: dict[str, Any], signer: str, signed_at: datetime) -> str:
    """The signed admission note in the hospital admission format, as a printable page."""
    from ..schemas import ADMISSION_HEARD_SECTIONS
    from .admission import ADMISSION_HEADER_FIELDS

    header = content.get("header") or {}
    record = "".join(
        f"<div class='kv'><span>{esc(label)}</span><b>{esc(str(header.get(key) or '-'))}</b></div>"
        for key, label in ADMISSION_HEADER_FIELDS
    )
    rows = []
    for key, label, many in ADMISSION_HEARD_SECTIONS:
        value = content.get(key)
        items = value if isinstance(value, list) else ([value] if value else [])
        texts = [
            esc(_text(v)) + (" <span class='src'>(from OPD report)</span>" if isinstance(v, dict) and v.get("origin") == "opd" else "")
            for v in items if _text(v)
        ]
        if not texts:
            body = "<p class='muted'>Not documented</p>"
        elif many and len(texts) > 1:
            body = "<ul>" + "".join(f"<li>{t}</li>" for t in texts) + "</ul>"
        else:
            body = f"<p>{texts[0]}</p>"
        rows.append(f"<section><h2>{esc(label)}</h2>{body}</section>")
    name = esc(str(header.get("name") or "Patient"))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Admission note - {name}</title>
<style>
@page {{ size: A4; margin: 16mm; }}
body {{ font-family: "Segoe UI", Tahoma, Arial, sans-serif; color: #10213d; margin: 32px auto; max-width: 760px; padding: 0 16px; font-size: 13.5px; line-height: 1.55; background: #fff; }}
header {{ border-bottom: 2px solid #0b3d91; padding-bottom: 10px; margin-bottom: 14px; }}
.hosp {{ font-size: 12px; font-weight: 700; letter-spacing: .5px; color: #0b3d91; text-transform: uppercase; }}
h1 {{ font-size: 20px; margin: 4px 0 8px; }}
h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: .3px; color: #0b3d91; margin: 16px 0 4px; }}
p {{ margin: 4px 0; }} ul {{ margin: 4px 0; padding-left: 20px; }}
.record {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid #c8d9f0; }}
.kv {{ display: flex; gap: 8px; padding: 5px 8px; border-bottom: 1px solid #e3ecf8; font-size: 12.5px; }}
.kv span {{ min-width: 170px; color: #4a5f80; }}
.muted, .src {{ color: #4a5f80; }}
footer {{ margin-top: 28px; padding-top: 10px; border-top: 1px solid #c8d9f0; font-size: 12px; color: #4a5f80; }}
.print {{ float: right; font: inherit; font-size: 12px; padding: 4px 12px; border: 1px solid #0b3d91; background: #fff; color: #0b3d91; cursor: pointer; }}
@media print {{ .print {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<header><button class="print" onclick="window.print()">Print</button>
<div class="hosp">MediBytes Hospital &middot; Admission</div><h1>Admission note</h1></header>
<div class="record">{record}</div>
{''.join(rows)}
<footer>Signed by {esc(signer)} on {esc(_when(signed_at))}. Drafted by MediBytes Analysis from the admission dictation; items marked "from OPD report" were taken from the patient's signed OPD report.</footer>
</body></html>"""
