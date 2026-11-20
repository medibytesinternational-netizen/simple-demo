"""The hospital investigation & radiology request form, one report per request.

  Request details                      <- the request and the record (study, priority, ward,
                                          diagnosis, allergies, creatinine / INR / other results)
  To be completed by the requesting doctor   <- the doctor who generates the report; contact,
                                          signature and pregnancy declaration are filled by hand
  To be completed by staff nurse or secretary <- blank, filled by hand
  Footer: appointment timings, radiology contact numbers by modality, provisional report

Anything not in the record prints as a blank line to be completed on paper.
"""

from __future__ import annotations

from datetime import datetime
from html import escape as esc
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Encounter, InvestigationRequest, Patient, TimelineEvent

REPORT_TYPE = "investigation_request_form"
TITLE = "Investigation & radiology request"

APPOINTMENT_TIMINGS = "7:45 AM to 7:00 PM"
# Radiology contact numbers by modality. Set the hospital's real extensions here.
MODALITY_CONTACTS = [("CT", ""), ("MRI", ""), ("Ultrasound", ""), ("X-ray", ""), ("Fluoroscopy", "")]

BLANK = "<span class='blank'></span>"


def _when(value: datetime | None) -> tuple[str, str]:
    return (value.strftime("%d %b %Y"), value.strftime("%H:%M")) if value else ("", "")


def _latest_labs(db: Session, patient_id: str) -> dict[str, dict[str, Any]]:
    events = db.scalars(
        select(TimelineEvent)
        .where(TimelineEvent.patient_id == patient_id, TimelineEvent.type == "lab_result")
        .order_by(TimelineEvent.occurred_at.desc())
    ).all()
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = event.payload or {}
        name = str(payload.get("name") or "").strip()
        if name and name.lower() not in latest:
            latest[name.lower()] = {**payload, "occurred_at": event.occurred_at}
    return latest


def _bed(bed: str) -> str:
    return bed if bed.lower().startswith("bed") else f"Bed {bed}"


def _lab_text(lab: dict[str, Any] | None) -> str:
    if not lab:
        return ""
    flag = str(lab.get("flag") or "").lower()
    day = lab["occurred_at"].strftime("%d %b %Y") if lab.get("occurred_at") else ""
    unit = str(lab.get("unit") or "").strip()
    text = f"{lab.get('value', '')} {unit if unit.lower() != 'none' else ''}".strip()
    if flag and flag not in ("normal", "unknown"):
        text += f" ({flag})"
    return f"{text}{f', {day}' if day else ''}"


def build(db: Session, request: InvestigationRequest, patient: Patient, encounter: Encounter | None,
          doctor: dict[str, str], made_at: datetime) -> dict[str, Any]:
    labs = _latest_labs(db, patient.id)
    creatinine = labs.pop("creatinine", None) or labs.pop("serum creatinine", None)
    inr = labs.pop("inr", None) or labs.pop("pt/inr", None)
    others = [f"{lab['name']}: {_lab_text(lab)}" for lab in labs.values()
              if str(lab.get("flag") or "").lower() not in ("", "normal", "unknown")]
    inpatient = bool(encounter and (encounter.kind or "").upper() == "IPD")
    ward = " / ".join(x for x in ((encounter.ward or "") if encounter else "",
                                  _bed(encounter.bed) if encounter and encounter.bed else "") if x)
    allergies = [a.get("substance", "") + (f" ({a['reaction']})" if a.get("reaction") else "")
                 for a in (request.allergies_to_verify or []) if a.get("substance")]
    if not allergies:
        allergies = [str(a.get("substance") if isinstance(a, dict) else a) for a in (patient.allergies or [])]
    return {
        "patient": {"name": patient.name, "hid": patient.mrn, "age": patient.age, "sex": patient.sex},
        "study": request.study or "",
        "kind": "Radiology" if request.request_type == "imaging" else "Investigation",
        "priority": (request.priority or "routine").lower(),
        "inpatient": inpatient,
        "ward": ward,
        "history": request.indication or "",
        # Provenance notes ("Raised from the doctor's progress note") are not clinical instructions.
        "instructions": "" if (request.instructions or "").lower().startswith("raised from") else (request.instructions or ""),
        "diagnosis": request.diagnosis or "",
        "allergies": [a for a in allergies if a],
        "creatinine": _lab_text(creatinine),
        "inr": _lab_text(inr),
        "other_labs": others,
        "requested_at": request.created_at,
        "consultant": (encounter.attending if encounter else "") or "",
        "doctor": doctor,
        "female": (patient.sex or "").strip().lower() in ("f", "female"),
        "made_at": made_at,
    }


def _box(on: bool, label: str) -> str:
    return f"<span class='opt{' on' if on else ''}'>{'&#9746;' if on else '&#9744;'} {esc(label)}</span>"


def render_html(form: dict[str, Any]) -> str:
    p = form["patient"]
    made_day, made_time = _when(form["made_at"])

    def row(label: str, body: str) -> str:
        return f"<tr><th>{esc(label)}</th><td>{body or BLANK}</td></tr>"

    def val(text: str) -> str:
        return esc(text) if text else ""

    priority = _box(form["priority"] == "routine", "Routine") + _box(form["priority"] in ("urgent", "stat", "emergency"), "Urgent")
    patient_type = (_box(form["inpatient"], "Inpatient") + (f" &nbsp;Ward: <b>{esc(form['ward'])}</b>" if form["inpatient"] and form["ward"] else (" &nbsp;Ward: " + BLANK if form["inpatient"] else ""))
                    + _box(not form["inpatient"], "Outpatient"))
    transport = "".join(_box(False, t) for t in ("Wheelchair", "Stretcher", "Walking", "Portable"))
    history = val(form["history"]) + (f"<br><span class='muted'>Look for: {esc(form['instructions'])}</span>" if form["instructions"] else "")
    allergies = esc(", ".join(form["allergies"])) if form["allergies"] else "No known allergy documented"
    labs = (f"<div>Serum creatinine: {val(form['creatinine']) or BLANK}</div>"
            f"<div>INR: {val(form['inr']) or BLANK}</div>"
            f"<div>Others: {esc('; '.join(form['other_labs'])) if form['other_labs'] else BLANK}</div>")
    report_day, _ = _when(form["requested_at"])
    doc = form["doctor"]
    pregnancy = (
        _box(False, "Pregnant") + _box(False, "Non-pregnant") + f"<div>Last menstrual period date: {BLANK}</div>"
        if form["female"] else "<span class='muted'>Not applicable (male patient)</span>"
    )
    contacts = "".join(f"<span class='contact'><b>{esc(m)}:</b> {esc(n) or BLANK}</span>" for m, n in MODALITY_CONTACTS)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(TITLE)} - {esc(form['study'] or 'Request')} - {esc(p['name'] or 'Patient')}</title>
<style>
@page {{ size: A4; margin: 14mm; }}
body {{ font-family: "Segoe UI", Tahoma, Arial, sans-serif; color: #10213d; margin: 32px auto; max-width: 780px; padding: 0 16px; font-size: 13px; line-height: 1.5; background: #fff; }}
header {{ border-bottom: 2px solid #0b3d91; padding-bottom: 10px; margin-bottom: 14px; }}
.hosp {{ font-size: 12px; font-weight: 700; letter-spacing: .5px; color: #0b3d91; text-transform: uppercase; }}
h1 {{ font-size: 20px; margin: 4px 0 8px; }} h2 {{ font-size: 12.5px; text-transform: uppercase; color: #0b3d91; margin: 16px 0 6px; }}
.record {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid #c8d9f0; }}
.kv {{ display: flex; gap: 8px; padding: 5px 8px; border-bottom: 1px solid #e3ecf8; font-size: 12.5px; }}
.kv span {{ color: #4a5f80; min-width: 90px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ text-align: left; vertical-align: top; padding: 6px 9px; border: 1px solid #c8d9f0; }}
th {{ background: #eef4fc; width: 230px; font-weight: 600; }}
.opt {{ display: inline-block; margin-right: 14px; color: #4a5f80; }} .opt.on {{ color: #10213d; font-weight: 700; }}
.blank {{ display: inline-block; min-width: 180px; border-bottom: 1px dotted #7a8aa6; height: 1em; }}
.tall {{ height: 70px; }}
.muted {{ color: #4a5f80; }}
footer {{ margin-top: 18px; border-top: 2px solid #0b3d91; padding-top: 8px; font-size: 12px; }}
.contact {{ display: inline-block; margin-right: 16px; }} .contact .blank {{ min-width: 70px; }}
.prov {{ border: 1px solid #c8d9f0; min-height: 110px; margin-top: 8px; padding: 6px 9px; }}
.print {{ float: right; font: inherit; font-size: 12px; padding: 4px 12px; border: 1px solid #0b3d91; background: #fff; color: #0b3d91; cursor: pointer; }}
@media print {{ .print {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<header><button class="print" onclick="window.print()">Print</button>
<div class="hosp">MediBytes Hospital &middot; {esc(form['kind'])}</div><h1>{esc(TITLE)} form</h1></header>
<div class="record">
<div class='kv'><span>Name</span><b>{esc(p['name'] or '-')}</b></div>
<div class='kv'><span>HID number</span><b>{esc(p['hid'] or '-')}</b></div>
<div class='kv'><span>Age / Sex</span><b>{esc(str(p['age'] or '-'))} / {esc(p['sex'] or '-')}</b></div>
<div class='kv'><span>Generated</span><b>{esc(made_day)} {esc(made_time)}</b></div>
</div>

<h2>Request details</h2>
<table>
{row("Investigation requested", f"<b>{esc(form['study'])}</b>" if form['study'] else "")}
{row("Priority", priority)}
{row("Type", patient_type)}
{row("Transport mode", transport)}
{row("Relevant history and examination (specific diagnosis or areas to be looked for)", history)}
{row("Clinical diagnosis", val(form['diagnosis']))}
{row("Allergies", allergies)}
{row("Relevant laboratory findings", labs)}
{row("Date of report", esc(report_day))}
</table>

<h2>To be completed by the doctor requesting the examination</h2>
<table>
{row("Doctor's name", esc(doc.get('name', '')))}
{row("Signature", "")}
{row("Designation", esc(doc.get('designation', '')))}
{row("Date", esc(made_day))}
{row("Time", esc(made_time))}
{row("Contact number", "")}
{row("Consultant's name", val(form['consultant']))}
{row("Pregnancy declaration (female patients)", pregnancy)}
</table>

<h2>To be completed by staff nurse or secretary</h2>
<table>
{row("Appointment date and time", "")}
{row("Informed by radiographer / radiology staff", "")}
<tr><th>Radiologist instruction or notes</th><td class="tall"></td></tr>
</table>

<footer>
<div><b>Appointment timings:</b> {esc(APPOINTMENT_TIMINGS)}</div>
<div style="margin-top:4px"><b>Radiology contact numbers:</b> {contacts}</div>
<h2>Provisional report</h2>
<div class="prov"></div>
</footer>
</body></html>"""
