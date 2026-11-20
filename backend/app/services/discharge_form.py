"""Discharge summary in the hospital's progress-note and handoff format.

A doctor (Admin, Senior or Junior) clicks "Generate report". Nothing is written by a model: the
form is assembled from the patient's signed record, so every line can be traced to a note, a
reading, a result or an order. Anything the record does not hold is printed as "Not documented"
for the doctor to complete by hand on the printed copy.

  Header:   Name, Sex, Ward, HID number
  Table:    Date and time | Progress note (one row per note on record, then the summary row)
  Summary row headings: pain score, site, intervention, C/S/B, subjective, objective, vitals, plan,
            doctor's name, signature and registration number
  Doctors handoff communication: complaints, vitals, investigations, medication, diet,
            handing over, taken over
"""

from __future__ import annotations

from datetime import datetime
from html import escape as esc
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Encounter, InvestigationRequest, Patient, TimelineEvent
from .identity import ROLE_LABELS, acting_user
from .progress import PROGRESS_FORMAT, notes_text

REPORT_TYPE = "discharge_report"
TITLE = "Discharge summary"
ND = "Not documented"
HEADER_FIELDS: list[tuple[str, str]] = [("name", "Name"), ("sex", "Sex"), ("ward", "Ward"), ("hid", "HID number")]
DIETS = ["Liquid", "Soft solids", "Normal", "Hypertensive", "Diabetic", "High protein", "Other"]
NOTE_TYPES = ("consult_note", "admission_note", "round_note", "progress_note", "nurse_progress_note", "nursing_note")
# High-risk medicines and narcotics, flagged in the handoff (by name match, lower case).
NARCOTICS = ("morphine", "fentanyl", "tramadol", "oxycodone", "pethidine", "codeine", "buprenorphine", "tapentadol")
HIGH_RISK = ("insulin", "heparin", "enoxaparin", "warfarin", "apixaban", "rivaroxaban", "potassium chloride",
             "digoxin", "amiodarone", "methotrexate", "vancomycin", "gentamicin", "noradrenaline", "midazolam",
             "magnesium sulphate", "dobutamine", "dopamine")


def header(patient: Patient, encounter: Encounter | None) -> dict[str, str]:
    return {
        "name": patient.name or "",
        "sex": patient.sex or "",
        "ward": (encounter.ward if encounter else "") or "",
        "hid": patient.mrn or "",
    }


def _items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for v in value:
            out.extend(_items(v))
        return out
    if isinstance(value, dict):
        return _items(value.get("text"))
    text = str(value).strip()
    return [text] if text else []


def _note_lines(event: TimelineEvent) -> list[str]:
    """What a note on record said, in plain lines."""
    p = event.payload or {}
    if p.get("format") == PROGRESS_FORMAT:
        return [line for line in notes_text(p).splitlines() if line.strip()]
    lines: list[str] = []
    for key, label in (("chief_complaint", "Complaint"), ("subjective", "Subjective"), ("examination", "Examination"),
                       ("objective", "Objective"), ("assessment", "Assessment"), ("plan", "Plan"),
                       ("note_claims", "")):
        values = _items(p.get(key))
        if values:
            lines.append(f"{label}: " + "; ".join(values) if label else "; ".join(values))
    if not lines and event.body_text:
        lines.append(event.body_text.strip())
    return lines


def _signed_by(event: TimelineEvent) -> str:
    signed = (event.payload or {}).get("signed_by") or {}
    return signed.get("name") or event.approved_by or event.author_name or ""


def _latest(events: list[TimelineEvent], *keys: str) -> list[str]:
    """The most recent non-empty value for any of ``keys`` (events are newest first)."""
    for event in events:
        p = event.payload or {}
        for key in keys:
            values = _items(p.get(key))
            if values:
                return values
    return []


def _pain(events: list[TimelineEvent]) -> dict[str, Any]:
    for event in events:
        p = event.payload or {}
        label = str(p.get("label") or p.get("category") or "").lower()
        score = p.get("pain_score")
        if score is None and "pain" in label:
            score = p.get("value")
        if score is None:
            continue
        try:
            value = float(score)
        except (TypeError, ValueError):
            continue
        return {"score": value, "site": str(p.get("pain_site") or p.get("site") or "").strip(),
                "intervention": str(p.get("pain_intervention") or p.get("intervention") or "").strip()}
    return {}


def _vitals(vitals: dict[str, Any] | None) -> dict[str, str]:
    p = (vitals or {}).get("payload") or {}
    bp = f"{p['systolic']}/{p['diastolic']} mmHg" if p.get("systolic") and p.get("diastolic") else ""
    return {
        "bp": bp,
        "pulse": f"{p['heart_rate']} /min" if p.get("heart_rate") else "",
        "temperature": f"{p['temperature_c']} °C" if p.get("temperature_c") else "",
        "rr": f"{p['respiratory_rate']} /min" if p.get("respiratory_rate") else "",
        "recorded_at": str(p.get("recorded_at") or (vitals or {}).get("occurred_at") or ""),
    }


def _risk(drug: str) -> str:
    name = drug.lower()
    if any(n in name for n in NARCOTICS):
        return "narcotic"
    if any(n in name for n in HIGH_RISK):
        return "high risk"
    return ""


def build(db: Session, patient: Patient, encounter: Encounter, state: dict[str, Any]) -> dict[str, Any]:
    """Everything the form prints, taken from the signed record."""
    events = list(db.scalars(
        select(TimelineEvent)
        .where(TimelineEvent.patient_id == patient.id, TimelineEvent.status == "approved")
        .order_by(TimelineEvent.occurred_at.desc())
    ))
    notes = [e for e in events if e.type in NOTE_TYPES]

    rows = []
    for event in reversed(notes):  # oldest first
        lines = _note_lines(event)
        if lines:
            rows.append({"time": event.occurred_at.isoformat() if event.occurred_at else "", "title": event.title or "",
                         "lines": lines, "signed_by": _signed_by(event)})

    progress = [e for e in notes if e.type in ("progress_note", "nurse_progress_note", "round_note")]
    current = _latest(progress, "subjective", "notes", "note_claims")
    reason = _latest([e for e in events if e.type in ("admission_note", "consult_note")], "chief_complaint")
    reason = reason or list(patient.problems or [])[:1]
    exam = _latest(notes, "examination", "objective", "local_examination")
    plan = _latest([e for e in notes if e.type != "nursing_note"], "plan")
    diet = _latest(events, "diet")
    pain = _pain([e for e in events if e.type in ("device_reading", "vitals", "nursing_note", "nurse_progress_note")])
    vitals = _vitals(state.get("vitals"))

    enc = state.get("encounter") or {}
    user = acting_user()

    labs = state.get("latest_labs") or []
    requests = db.scalars(select(InvestigationRequest).where(InvestigationRequest.patient_id == patient.id)).all()
    meds = [e for e in events if e.type == "med_order" and (e.payload or {}).get("kind") != "home"]
    added, stopped = [], []
    for e in reversed(meds):
        p = e.payload or {}
        drug = str(p.get("drug") or "").strip()
        if not drug:
            continue
        line = " ".join(x for x in (drug, str(p.get("dose") or ""), str(p.get("route") or ""), str(p.get("frequency") or "")) if x)
        entry = {"text": line, "risk": _risk(drug)}
        (stopped if str(p.get("status") or "").lower() in ("stopped", "held", "discontinued") else added).append(entry)
    for e in notes:  # holds and stops decided on the round
        for action in (e.payload or {}).get("plan_actions") or []:
            if isinstance(action, dict) and action.get("action") in ("hold", "stop") and action.get("drug"):
                text = f"{action['drug']} ({action['action']})"
                if not any(s["text"].startswith(action["drug"]) for s in stopped):
                    stopped.append({"text": text, "risk": _risk(action["drug"])})

    return {
        "header": header(patient, encounter),
        "rows": rows,
        "summary": {
            "pain_score": f"{pain['score']:g} / 10" if pain else "",
            "pain_site": pain.get("site", ""),
            "pain_high": bool(pain) and pain["score"] >= 4,
            "intervention": pain.get("intervention", ""),
            "consultant": enc.get("attending") or "",
            "unit": enc.get("ward") or "",
            "bed": enc.get("bed") or "",
            "reason": reason,
            "current": current,
            "examination": exam,
            "vitals": vitals,
            "plan": plan,
        },
        "handoff": {
            "complaints": current,
            "vitals": vitals,
            "ordered": [f"{r.study or r.request_type} ({r.priority}, {r.status})" for r in requests],
            "received": [f"{l['name']} {l.get('value')} {l.get('unit') or ''}".strip() for l in labs],
            "critical": [f"{l['name']} {l.get('value')} {l.get('unit') or ''} ({l.get('flag')})".strip()
                         for l in labs if l.get("flag") in ("critical", "high", "low", "abnormal")],
            "added": added,
            "stopped": stopped,
            "diet": diet,
        },
        "doctor": {"name": user.name, "role": ROLE_LABELS.get(user.role, user.role)},
    }


def when(value: str | datetime | None) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", ""))
        except ValueError:
            return value
    return value.strftime("%d %b %Y, %H:%M")


def _or_nd(values: list[str] | str) -> str:
    if isinstance(values, str):
        return esc(values) if values.strip() else f"<span class='nd'>{ND}</span>"
    return "; ".join(esc(v) for v in values) if values else f"<span class='nd'>{ND}</span>"


def _vitals_html(v: dict[str, str]) -> str:
    parts = [("BP", v["bp"]), ("PR", v["pulse"]), ("Temp", v["temperature"]), ("RR", v["rr"])]
    text = " &nbsp; ".join(f"<b>{k}</b> {esc(x) if x else '-'}" for k, x in parts)
    return text + (f" <span class='muted'>({esc(when(v['recorded_at']))})</span>" if v.get("recorded_at") else "")


def _meds_html(items: list[dict[str, str]]) -> str:
    if not items:
        return "None recorded"
    return "; ".join(esc(m["text"]) + (f" <b class='risk'>[{esc(m['risk'])}]</b>" if m["risk"] else "") for m in items)


def render_html(form: dict[str, Any], made_at: datetime) -> str:
    head, s, h, doc = form["header"], form["summary"], form["handoff"], form["doctor"]
    record = "".join(
        f"<div class='kv'><span>{esc(label)}</span><b>{esc(str(head.get(key) or '-'))}</b></div>"
        for key, label in HEADER_FIELDS
    )
    def row(r: dict[str, Any]) -> str:
        signed = f"<div class='muted'>Signed: {esc(r['signed_by'])}</div>" if r["signed_by"] else ""
        lines = "<br>".join(esc(x) for x in r["lines"])
        return (f"<tr><td class='t'>{esc(when(r['time']))}</td>"
                f"<td><div class='rt'>{esc(r['title'])}</div>{lines}{signed}</td></tr>")

    earlier = "".join(row(r) for r in form["rows"])
    if s["pain_score"]:
        intervention = esc(s["intervention"]) if s["intervention"] else (
            f"<span class='nd'>Required (pain score four or above): {ND}</span>" if s["pain_high"] else "Not required (pain score below four)")
    else:
        intervention = f"<span class='nd'>{ND}</span>"
    csb = (f"<b>C</b> {esc(s['consultant'] or '-')} &nbsp; <b>S</b> {esc(s['unit'] or '-')} &nbsp; "
           f"<b>B</b> {esc(s['bed'] or '-')}")
    summary = f"""
<dl class="pn">
<dt>Pain score</dt><dd>{_or_nd(s['pain_score'])}</dd>
<dt>Site</dt><dd>{_or_nd(s['pain_site'])}</dd>
<dt>Intervention if pain score is four and above</dt><dd>{intervention}</dd>
<dt>Consultant, unit and bed</dt><dd>{csb}</dd>
<dt>Subjective</dt><dd><i>Reason for admission:</i> {_or_nd(s['reason'])}<br><i>Current complaints:</i> {_or_nd(s['current'])}</dd>
<dt>Objective</dt><dd><i>Local examination findings:</i> {_or_nd(s['examination'])}</dd>
<dt>Vitals</dt><dd>{_vitals_html(s['vitals'])}</dd>
<dt>Plan</dt><dd>{_or_nd(s['plan'])}</dd>
<dt>Doctor's name, signature and registration number</dt><dd>{esc(doc['name'])} ({esc(doc['role'])}) &nbsp; Signature: <span class='line'></span> &nbsp; Reg. no.: <span class='line'></span></dd>
</dl>"""
    complaints = ("Yes: " + "; ".join(esc(c) for c in h["complaints"])) if h["complaints"] else "No"
    diets = " &nbsp; ".join(
        f"<span class='box'>{'&#9745;' if any(d.lower() in x.lower() for x in h['diet']) else '&#9744;'}</span> {d}" for d in DIETS
    )
    diet_text = f"<br>{_or_nd(h['diet'])}" if h["diet"] else f" <span class='nd'>({ND})</span>"
    made = esc(when(made_at))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{TITLE} - {esc(head.get('name') or 'Patient')}</title>
<style>
@page {{ size: A4; margin: 14mm; }}
body {{ font-family: "Segoe UI", Tahoma, Arial, sans-serif; color: #10213d; margin: 32px auto; max-width: 860px; padding: 0 16px; font-size: 13px; line-height: 1.5; background: #fff; }}
header {{ border-bottom: 2px solid #0b3d91; padding-bottom: 10px; margin-bottom: 12px; }}
.hosp {{ font-size: 12px; font-weight: 700; letter-spacing: .5px; color: #0b3d91; text-transform: uppercase; }}
h1 {{ font-size: 20px; margin: 4px 0 6px; }} h2 {{ font-size: 15px; margin: 22px 0 8px; color: #0b3d91; }}
.record {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid #c8d9f0; margin-bottom: 10px; }}
.kv {{ display: flex; flex-direction: column; padding: 6px 8px; font-size: 12.5px; }}
.kv span {{ color: #4a5f80; font-size: 11.5px; }}
.instr {{ border: 1px solid #c8d9f0; background: #f5f8fd; padding: 6px 10px; font-size: 12px; margin-bottom: 12px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ text-align: left; vertical-align: top; padding: 6px 8px; border: 1px solid #c8d9f0; }}
th {{ background: #eef4fc; }} td.t {{ white-space: nowrap; width: 130px; }}
tr {{ break-inside: avoid; }} .rt {{ font-weight: 600; }}
dl.pn {{ display: grid; grid-template-columns: 210px 1fr; margin: 0; }}
dl.pn dt {{ font-weight: 600; padding: 4px 8px 4px 0; border-top: 1px solid #e3ecf8; }}
dl.pn dd {{ margin: 0; padding: 4px 0; border-top: 1px solid #e3ecf8; }}
.nd {{ color: #9a5b00; font-style: italic; }} .risk {{ color: #b42318; }}
.muted {{ color: #4a5f80; font-size: 11.5px; }}
.line {{ display: inline-block; min-width: 140px; border-bottom: 1px solid #10213d; height: 1em; }}
.note {{ border: 1px solid #f0c36d; background: #fff8e6; padding: 6px 10px; font-size: 12px; margin-top: 10px; }}
footer {{ margin-top: 22px; padding-top: 10px; border-top: 1px solid #c8d9f0; font-size: 11.5px; color: #4a5f80; }}
.print {{ float: right; font: inherit; font-size: 12px; padding: 4px 12px; border: 1px solid #0b3d91; background: #fff; color: #0b3d91; cursor: pointer; }}
@media print {{ .print {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<header><button class="print" onclick="window.print()">Print</button>
<div class="hosp">MediBytes Hospital</div><h1>{TITLE}</h1></header>
<div class="record">{record}</div>
<div class="instr">Progress notes must be legible. All notes must be in SOAP format: Subjective, Objective findings, Assessment, Plan.</div>
<table><thead><tr><th>Date and time</th><th>Progress note</th></tr></thead><tbody>
{earlier}
<tr><td class='t'>{made}</td><td>{summary}</td></tr>
</tbody></table>
<div class="note">Intervention required for pain score four and above. After intervention, re-document the pain score within one hour.</div>

<h2>Doctors handoff communication</h2>
<dl class="pn">
<dt>Complaints</dt><dd>{complaints}</dd>
<dt>Vitals</dt><dd>{_vitals_html(h['vitals'])}</dd>
<dt>Investigations</dt><dd><i>Ordered:</i> {esc('; '.join(h['ordered'])) or 'None recorded'}<br><i>Received:</i> {esc('; '.join(h['received'])) or 'None recorded'}<br><i>Critical or abnormal reports:</i> {esc('; '.join(h['critical'])) or 'None'}</dd>
<dt>Medication</dt><dd><i>Added:</i> {_meds_html(h['added'])}<br><i>Stopped:</i> {_meds_html(h['stopped'])}<br><span class='muted'>High-risk drugs and narcotics are marked.</span></dd>
<dt>Diet</dt><dd>{diets}{diet_text}</dd>
<dt>Handing over</dt><dd>{esc(doc['name'])} &nbsp; Signature: <span class='line'></span> &nbsp; {made}</dd>
<dt>Taken over</dt><dd>Name: <span class='line'></span> &nbsp; Signature: <span class='line'></span> &nbsp; Date and time: <span class='line'></span></dd>
</dl>
<footer>Generated by {esc(doc['name'])} on {made} from the patient's signed record. Lines marked "{ND}" are not in the record and are to be completed by hand.</footer>
</body></html>"""
