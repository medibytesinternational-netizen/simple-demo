from __future__ import annotations

import re
from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BillLineItem, Document, DocumentRequest, Encounter, Patient
from .timeline import list_events

# Note types that can assert "no known allergies" (any approved note, not one seeded shape).
ALLERGY_NOTE_TYPES = {
    "admission_note",
    "progress_note",
    "round_note",
    "consult_note",
    "nursing_note",
    "nursing_summary",
}
NO_ALLERGY_RE = re.compile(r"no known (drug )?allergies", re.IGNORECASE)
HOLD_VERBS = r"(?:stop|hold|withhold|discontinue)"
NEGATION_BEFORE_RE = re.compile(r"(?:\bnot|n't|\bnever|\bno)\s+(?:to\s+|be\s+)?$", re.IGNORECASE)


def _claim_texts(payload: dict[str, Any]) -> list[str]:
    """Plain claim texts a drafted note carries (strings or {"text": ...})."""
    out: list[str] = []
    claims = payload.get("note_claims") or []
    if isinstance(claims, list):
        for claim in claims:
            if isinstance(claim, str):
                out.append(claim)
            elif isinstance(claim, dict) and isinstance(claim.get("text"), str):
                out.append(claim["text"])
    return out


def _sentences(event: Any) -> list[str]:
    """Verbatim sentences of an approved note: its body text, then its claim texts."""
    out: list[str] = []
    for text in [event.body_text or "", *_claim_texts(event.payload or {})]:
        out.extend(part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip())
    return out


def _evidence(event: Any, quote: str | None) -> dict[str, Any]:
    return {"event_id": event.id, "type": event.type, "title": event.title, "quote": quote or ""}


def claim_prep(
    db: Session,
    patient: Patient,
    encounter: Encounter,
    state: dict[str, Any],
) -> dict[str, Any]:
    all_events = list_events(db, patient.id, encounter.id, approved_only=True, limit=1000)
    # A superseded note no longer speaks for the record, so it cannot raise a contradiction.
    events = [event for event in all_events if event.status == "approved"]
    bill = list(
        db.scalars(
            select(BillLineItem)
            .where(BillLineItem.patient_id == patient.id, BillLineItem.encounter_id == encounter.id)
            .order_by(BillLineItem.billed_at)
        )
    )
    documents = list(
        db.scalars(
            select(Document)
            .where(Document.patient_id == patient.id, Document.encounter_id == encounter.id)
        )
    )
    requests = list(
        db.scalars(
            select(DocumentRequest)
            .where(DocumentRequest.patient_id == patient.id, DocumentRequest.encounter_id == encounter.id)
        )
    )
    bill_event = next((event for event in events if event.type == "billing"), None)
    discharge_event = next((event for event in events if event.type == "discharge_summary"), None)
    request_event = next((event for event in events if event.type == "document_request"), None)

    pre_auth_doc_ids = {
        doc.id for doc in documents if doc.doc_type == "pre_auth" and doc.ocr_status in {"confirmed", "reviewed"}
    }
    # A matched request counts only when its document is a pre-authorisation of this patient.
    for request in requests:
        if request.status == "matched" and request.request_type == "pre_auth" and request.matched_document_id:
            matched = db.get(Document, request.matched_document_id)
            if matched and matched.patient_id == patient.id and matched.doc_type == "pre_auth":
                pre_auth_doc_ids.add(matched.id)
    pre_auth_present = bool(pre_auth_doc_ids)
    pre_auth_evidence = [event.id for event in events if event.document_id and event.document_id in pre_auth_doc_ids]
    if request_event and request_event.id not in pre_auth_evidence:
        pre_auth_evidence.append(request_event.id)
    lab_docs_present = any(lab["event_id"] for lab in state.get("latest_labs", []))
    bill_present = bool(bill)

    required_docs = [
        {
            "key": "signed_discharge",
            "label": "Signed discharge summary",
            "present": bool(discharge_event),
            "evidence_event_ids": [discharge_event.id] if discharge_event else [],
        },
        {
            "key": "itemized_bill",
            "label": "Itemized bill",
            "present": bill_present,
            "evidence_event_ids": [bill_event.id] if bill_event else [],
        },
        {
            "key": "pre_auth",
            "label": "Pre-authorization approval",
            "present": pre_auth_present,
            "evidence_event_ids": pre_auth_evidence,
        },
        {
            "key": "lab_reports",
            "label": "Laboratory reports",
            "present": bool(lab_docs_present),
            "evidence_event_ids": [lab["event_id"] for lab in state.get("latest_labs", [])[:2]],
        },
    ]
    missing = [doc for doc in required_docs if not doc["present"]]

    documented_procedures = []
    for event in events:
        if event.type == "procedure":
            payload = event.payload or {}
            documented_procedures.append(
                {
                    "procedure": payload.get("procedure", event.title),
                    "code": payload.get("code", ""),
                    "event_id": event.id,
                    "evidence_event_ids": [event.id],
                }
            )

    billed_text = " ".join(str(item.description).lower() for item in bill)
    unbilled = [
        item
        for item in documented_procedures
        if str(item["procedure"]).lower() not in billed_text
    ]
    unsupported = [
        {
            "id": item.id,
            "code": item.code,
            "description": item.description,
            "amount": item.amount,
            "documentation_event_ids": item.documentation_event_ids or [],
            "evidence_event_ids": [bill_event.id] if bill_event else [],
        }
        for item in bill
        if not (item.documentation_event_ids or [])
    ]
    underbilled = [
        {
            "id": item.id,
            "code": item.code,
            "description": item.description,
            "billed_amount": item.amount,
            "expected_amount": item.expected_amount,
            "variance": round((item.expected_amount or 0) - item.amount, 2),
            "documentation_event_ids": item.documentation_event_ids or [],
            "evidence_event_ids": [bill_event.id] if bill_event else [],
        }
        for item in bill
        if item.expected_amount is not None and item.expected_amount > item.amount
    ]

    event_by_id = {event.id: event for event in all_events}
    supporting_types = {
        "procedure",
        "medication_administration",
        "nursing_note",
        "admission_note",
        "discharge_summary",
    }
    contradictions: list[dict[str, Any]] = []

    allergy_events = [event for event in events if event.type == "allergy_record"]
    asserting_notes: list[tuple[Any, str]] = []
    for event in events:
        if event.type not in ALLERGY_NOTE_TYPES:
            continue
        quote = next((s for s in _sentences(event) if NO_ALLERGY_RE.search(s)), None)
        if quote is None and (event.payload or {}).get("assertion") == "no_known_allergies":
            quote = (_sentences(event) or [event.title])[0]
        if quote is not None:
            asserting_notes.append((event, quote))
    if allergy_events:
        allergy = allergy_events[0]
        substance = str((allergy.payload or {}).get("substance") or allergy.title)
        for number, (note, quote) in enumerate(asserting_notes):
            contradictions.append(
                {
                    "id": "contradiction_allergy" if number == 0 else f"contradiction_allergy_{note.id}",
                    "kind": "clinical_record",
                    "title": f"Allergy record contradicts a {note.type.replace('_', ' ')}",
                    "explanation": (
                        f"An allergy to {substance} is documented in the record, while the "
                        f"{note.type.replace('_', ' ')} \"{note.title}\" states no known allergies. "
                        "The claim pack must not present these as compatible."
                    ),
                    "evidence_event_ids": [allergy.id, note.id],
                    "evidence": [_evidence(allergy, allergy.body_text or allergy.title), _evidence(note, quote)],
                }
            )

    active_meds = {str(item.get("drug", "")).lower(): item for item in state.get("active_meds", [])}
    seen_hold: set[str] = set()

    def add_hold(drug: str, note: Any, quote: str | None, via: str) -> None:
        med = active_meds[drug]
        med_event = event_by_id.get(med.get("event_id"))
        contradictions.append(
            {
                "id": f"contradiction_plan_{drug}",
                "kind": "medication",
                "title": f"Open plan action conflicts with the active {med.get('drug')} order"
                if via == "plan_action"
                else f"A note says to stop {med.get('drug')}, but the order is still active",
                "explanation": (
                    f"The documented plan says hold {med.get('drug')}, but it remains active "
                    "in the inpatient medication list with no documented resolution."
                ),
                "evidence_event_ids": [note.id, med.get("event_id")],
                "evidence": [
                    _evidence(note, quote),
                    _evidence(med_event, med_event.body_text or med_event.title)
                    if med_event
                    else {"event_id": med.get("event_id"), "type": "med_order", "title": str(med.get("drug")), "quote": ""},
                ],
            }
        )

    for event in events:
        plan_drugs: set[str] = set()
        for action in (event.payload or {}).get("plan_actions", []) or []:
            if not isinstance(action, dict):
                continue
            drug = str(action.get("drug", "")).lower()
            plan_drugs.add(drug)
            if (
                action.get("status") == "open"
                and action.get("action") == "hold"
                and drug in active_meds
                and drug not in seen_hold
            ):
                seen_hold.add(drug)
                quote = next((s for s in _sentences(event) if drug in s.lower()), None)
                add_hold(drug, event, quote or f"Plan action: hold {action.get('drug')}", "plan_action")
        if event.type != "round_note":
            continue
        for drug in active_meds:
            # A plan action for this drug on this note is authoritative: resolving it clears the gap.
            if not drug or drug in seen_hold or drug in plan_drugs:
                continue
            pattern = re.compile(rf"\b{HOLD_VERBS}\s+(?:the\s+)?{re.escape(drug)}\b", re.IGNORECASE)
            for sentence in _sentences(event):
                match = pattern.search(sentence)
                if match and not NEGATION_BEFORE_RE.search(sentence[: match.start()]):
                    seen_hold.add(drug)
                    add_hold(drug, event, sentence, "note_text")
                    break

    for item in bill:
        supporting_events = [
            event_by_id[event_id]
            for event_id in (item.documentation_event_ids or [])
            if event_id in event_by_id
        ]
        if supporting_events and not any(event.type in supporting_types for event in supporting_events):
            contradictions.append(
                {
                    "id": f"contradiction_support_{item.id}",
                    "kind": "billing_documentation",
                    "title": f"Billed item has only narrative support: {item.description}",
                    "explanation": (
                        "The billed item points only to a narrative note. It has no administration, "
                        "procedure, nursing or discharge record to support the charge."
                    ),
                    "evidence_event_ids": [event.id for event in supporting_events],
                    "evidence": [_evidence(event, (_sentences(event) or [event.title])[0]) for event in supporting_events],
                }
            )

    total = sum(item.amount for item in bill)
    expected_total = sum(item.expected_amount or item.amount for item in bill)
    status = "review_ready" if not missing and not unsupported and not contradictions else "on_hold"
    if contradictions:
        status = "needs_clarification"

    return {
        "status": status,
        "required_documents": required_docs,
        "missing_documents": missing,
        "documented_procedures": documented_procedures,
        "billed_items": [
            {
                "id": item.id,
                "code": item.code,
                "description": item.description,
                "amount": item.amount,
                "expected_amount": item.expected_amount,
                "documentation_event_ids": item.documentation_event_ids or [],
            }
            for item in bill
        ],
        "unbilled_procedures": unbilled,
        "underbilled_items": underbilled,
        "unsupported_items": unsupported,
        "contradictions": contradictions,
        "tpa_review": {
            "status": "needs_clarification" if contradictions else "ready_for_review",
            "reviewer": None,
            "contradiction_count": len(contradictions),
            "evidence_event_ids": sorted(
                {
                    event_id
                    for contradiction in contradictions
                    for event_id in contradiction.get("evidence_event_ids", [])
                }
            ),
        },
        "total_amount": total,
        "expected_total_amount": expected_total,
        "underbilled_amount": round(expected_total - total, 2),
        "bill_event_id": bill_event.id if bill_event else None,
        "discharge_signed": bool(discharge_event),
    }


def _gap_rows(prep: dict[str, Any]) -> list[tuple[str, str, str, list[str]]]:
    """Every gap in the pack as (kind, item, what is wrong, evidence event ids)."""
    gaps: list[tuple[str, str, str, list[str]]] = []
    for item in prep.get("missing_documents", []):
        gaps.append(("Missing document", str(item.get("label", "")), "Required before review", list(item.get("evidence_event_ids", []))))
    for item in prep.get("contradictions", []):
        gaps.append(
            ("Contradiction", str(item.get("title", "")), str(item.get("explanation", "")), list(item.get("evidence_event_ids", [])))
        )
    for item in prep.get("unbilled_procedures", []):
        gaps.append(("Unbilled", str(item.get("procedure", "")), "Documented, not billed", list(item.get("evidence_event_ids", []))))
    for item in prep.get("unsupported_items", []):
        gaps.append(
            ("Unsupported", str(item.get("description", "")), "Billed, no supporting documentation", list(item.get("evidence_event_ids", [])))
        )
    for item in prep.get("underbilled_items", []):
        gaps.append(
            (
                "Underbilled",
                str(item.get("description", "")),
                f"Underbilled: {item.get('variance', 0):,.0f} below expected",
                list(item.get("evidence_event_ids", [])),
            )
        )
    return gaps


def claim_pack_html(patient: Patient, encounter: Encounter, prep: dict[str, Any]) -> str:
    def rows(items: list[dict[str, Any]], label_key: str, value_key: str) -> str:
        if not items:
            return '<tr><td colspan="2" class="muted">None</td></tr>'
        return "".join(
            f"<tr><td>{escape(str(item.get(label_key, '')))}</td>"
            f"<td>{escape(str(item.get(value_key, '')))}</td></tr>"
            for item in items
        )

    def ids(values: list[str]) -> str:
        clean = [str(value) for value in values if value]
        return escape(", ".join(clean)) if clean else '<span class="muted">no source</span>'

    doc_rows = "".join(
        f"<tr><td>{escape(str(item['label']))}</td>"
        f"<td class='{'ok' if item['present'] else 'bad'}'>"
        f"{'Present' if item['present'] else 'MISSING'}</td>"
        f"<td>{ids(item.get('evidence_event_ids', []))}</td></tr>"
        for item in prep["required_documents"]
    )
    contradiction_rows = "".join(
        f"<tr><td>{escape(str(item.get('title', '')))}</td>"
        f"<td class='bad'>{escape(str(item.get('explanation', '')))}"
        + "".join(
            f"<div class='meta'>{escape(str(ev.get('event_id', '')))}: &ldquo;{escape(str(ev.get('quote', '')))}&rdquo;</div>"
            for ev in item.get("evidence", [])
        )
        + f"</td><td>{ids(item.get('evidence_event_ids', []))}</td></tr>"
        for item in prep.get("contradictions", [])
    ) or '<tr><td colspan="3" class="muted">No contradictions found</td></tr>'
    underbilled_rows = "".join(
        f"<tr><td>{escape(str(item['description']))}</td>"
        f"<td>{item['billed_amount']:,.0f}</td><td>{item['expected_amount']:,.0f}</td></tr>"
        for item in prep.get("underbilled_items", [])
    ) or '<tr><td colspan="3" class="muted">No underbilled items</td></tr>'
    gap_rows = "".join(
        f"<tr><td>{escape(kind)}</td><td>{escape(item)}</td><td class='bad'>{escape(what)}</td><td>{ids(evidence)}</td></tr>"
        for kind, item, what, evidence in _gap_rows(prep)
    ) or '<tr><td colspan="4" class="muted">No documentation gaps</td></tr>'
    status = escape(str(prep.get("status", "unknown")).replace("_", " "))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Claim pack — {escape(patient.name)}</title>
<style>
  body {{ font-family: Inter, Arial, sans-serif; margin: 40px; color: #16181d; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  .watermark {{ border: 2px solid #c62828; color: #c62828; padding: 8px 12px;
                display: inline-block; font-weight: 700; margin: 16px 0; letter-spacing: .08em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
  th, td {{ border-bottom: 1px solid #e3e6eb; padding: 8px 6px; text-align: left; font-size: 13px; }}
  th {{ background: #f7f8fa; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }}
  .ok {{ color: #1b7f3b; font-weight: 600; }}
  .bad {{ color: #c62828; font-weight: 600; }}
  .muted {{ color: #6b7280; }}
  .meta {{ color: #6b7280; font-size: 12px; }}
</style></head>
<body>
  <h1>Claim pack — clinical review copy</h1>
  <div class="meta">{escape(patient.name)} · {escape(patient.mrn)} · {escape(encounter.ward or '')} {escape(encounter.bed or '')}</div>
  <div class="watermark">REVIEW ONLY · NOT SUBMITTED</div>
  <p><strong>Review only: nothing is submitted.</strong></p>
  <div class="meta">Status: {status} · TPA review status: {escape(str(prep.get('tpa_review', {}).get('status', 'unknown')))} · contradictions: {len(prep.get('contradictions', []))}</div>
  <h2>Documentation gaps</h2>
  <table><thead><tr><th>Kind</th><th>Item</th><th>Gap</th><th>Evidence</th></tr></thead><tbody>{gap_rows}</tbody></table>
  <h2>Contradictions before submission</h2>
  <table><thead><tr><th>Issue</th><th>Explanation</th><th>Evidence</th></tr></thead><tbody>{contradiction_rows}</tbody></table>
  <h2>Required documents</h2>
  <table><thead><tr><th>Document</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{doc_rows}</tbody></table>
  <h2>Billed items</h2>
  <table><thead><tr><th>Description</th><th>Amount</th></tr></thead><tbody>
    {rows(prep['billed_items'], 'description', 'amount')}
  </tbody></table>
  <p><strong>Billed total:</strong> INR {prep['total_amount']:,.0f} · <strong>Expected total:</strong> INR {prep.get('expected_total_amount', prep['total_amount']):,.0f}</p>
  <h2>Underbilled line items</h2>
  <table><thead><tr><th>Description</th><th>Billed</th><th>Expected</th></tr></thead><tbody>{underbilled_rows}</tbody></table>
  <h2>Documented procedures</h2>
  <table><thead><tr><th>Procedure</th><th>Code</th></tr></thead><tbody>
    {rows(prep['documented_procedures'], 'procedure', 'code')}
  </tbody></table>
  <p class="muted">Generated by the MediBytes ARD demo. Synthetic data. No claim was submitted.</p>
</body></html>"""
