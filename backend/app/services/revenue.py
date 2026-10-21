from __future__ import annotations

from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BillLineItem, Document, DocumentRequest, Encounter, Patient
from .timeline import list_events


def _lab(state: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next(
        (lab for lab in state.get("latest_labs", []) if str(lab["name"]).lower() == name.lower()),
        None,
    )


def _med_label(med: dict[str, Any]) -> str:
    return " ".join(
        str(med.get(key, "")).strip()
        for key in ("drug", "dose", "route", "frequency")
        if str(med.get(key, "")).strip()
    )


def reconciliation(state: dict[str, Any]) -> dict[str, Any]:
    home = state.get("home_meds", [])
    current = state.get("active_meds", [])
    current_by_drug: dict[str, dict[str, Any]] = {}
    for med in current:
        current_by_drug[str(med["drug"]).lower()] = med
    home_by_drug = {str(med["drug"]).lower(): med for med in home}
    discrepancies: list[dict[str, Any]] = []
    egfr = _lab(state, "eGFR")

    def add(
        *,
        ident: str,
        kind: str,
        home_med: str,
        current_order: str | None,
        explanation: str,
        evidence: list[str],
        field: str = "",
        home_value: str = "",
        current_value: str = "",
        recommended_action: str = "Review and document the reconciliation decision.",
    ) -> None:
        discrepancies.append(
            {
                "id": ident,
                "kind": kind,
                "home_med": home_med,
                "current_order": current_order,
                "field": field,
                "home_value": home_value,
                "current_value": current_value,
                "explanation": explanation,
                "recommended_action": recommended_action,
                "evidence_event_ids": evidence,
            }
        )

    metformin = current_by_drug.get("metformin")
    if metformin and egfr:
        try:
            egfr_value = float(egfr["value"])
        except (TypeError, ValueError):
            egfr_value = None
        if egfr_value is not None and egfr_value < 30:
            add(
                ident="disc_metformin",
                kind="contraindicated",
                home_med="Metformin 1 g BD",
                current_order=f"{metformin.get('dose', '')} {metformin.get('frequency', '')}".strip(),
                explanation=(
                    f"Metformin remains active while eGFR is {egfr_value:g}. "
                    "It should be reviewed and stopped in severe renal impairment."
                ),
                evidence=[metformin["event_id"], egfr["event_id"]],
                field="renal safety",
                home_value="eGFR 22 mL/min/1.73m²",
                current_value="Metformin active",
                recommended_action="Stop metformin and document the rationale; consider an alternative agent.",
            )

    for drug, med in home_by_drug.items():
        current_med = current_by_drug.get(drug)
        if not current_med:
            add(
                ident=f"disc_omitted_{drug.replace(' ', '_')}",
                kind="omitted",
                home_med=_med_label(med),
                current_order=None,
                explanation="Home medication is not present on the current inpatient order list.",
                evidence=[med["event_id"]],
                field="presence",
                home_value="Active at home",
                current_value="Not ordered",
                recommended_action="Confirm whether the medicine should be continued, held or stopped.",
            )
            continue

        for field, kind, label in (
            ("dose", "dose_changed", "dose"),
            ("route", "route_changed", "route"),
            ("frequency", "frequency_changed", "frequency"),
            ("indication", "indication_missing", "indication"),
        ):
            home_value = str(med.get(field, "") or "").strip()
            current_value = str(current_med.get(field, "") or "").strip()
            if not home_value:
                continue
            if field == "indication" and not current_value:
                add(
                    ident=f"disc_indication_{drug.replace(' ', '_')}",
                    kind=kind,
                    home_med=_med_label(med),
                    current_order=_med_label(current_med),
                    explanation="The current inpatient order has no documented indication.",
                    evidence=[med["event_id"], current_med["event_id"]],
                    field=label,
                    home_value=home_value,
                    current_value="Not documented",
                    recommended_action="Document the indication for the current order.",
                )
            elif current_value and home_value.lower() != current_value.lower():
                add(
                    ident=f"disc_{field}_{drug.replace(' ', '_')}",
                    kind=kind,
                    home_med=_med_label(med),
                    current_order=_med_label(current_med),
                    explanation=f"{label.title()} differs between the home list and the current inpatient order.",
                    evidence=[med["event_id"], current_med["event_id"]],
                    field=label,
                    home_value=home_value,
                    current_value=current_value,
                    recommended_action=f"Confirm the intended {label} with the prescriber.",
                )

    warfarin = current_by_drug.get("warfarin") or home_by_drug.get("warfarin")
    ibuprofen = current_by_drug.get("ibuprofen") or home_by_drug.get("ibuprofen")
    if warfarin and ibuprofen:
        add(
            ident="disc_warfarin_ibuprofen",
            kind="interaction",
            home_med="Warfarin + Ibuprofen",
            current_order="Both active",
            explanation=(
                "Concurrent warfarin and ibuprofen increases bleeding risk, especially with CKD. "
                "Review and stop the NSAID unless there is a documented reason."
            ),
            evidence=[warfarin["event_id"], ibuprofen["event_id"]],
            field="interaction",
            home_value="Warfarin active",
            current_value="Ibuprofen active",
            recommended_action="Review the pair, stop the NSAID where possible, and document the decision.",
        )

    return {
        "discrepancies": discrepancies,
        "home_medications": home,
        "current_medications": current,
        "summary": f"{len(discrepancies)} discrepancies found by deterministic comparison.",
    }


def claim_prep(
    db: Session,
    patient: Patient,
    encounter: Encounter,
    state: dict[str, Any],
) -> dict[str, Any]:
    events = list_events(db, patient.id, encounter.id, approved_only=True, limit=1000)
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

    pre_auth_present = any(
        doc.doc_type == "pre_auth" and doc.ocr_status in {"confirmed", "reviewed"} for doc in documents
    ) or any(request.status == "matched" and request.request_type == "pre_auth" for request in requests)
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
            "evidence_event_ids": [request_event.id] if request_event else [],
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

    event_by_id = {event.id: event for event in events}
    supporting_types = {
        "procedure",
        "medication_administration",
        "nursing_note",
        "admission_note",
        "discharge_summary",
    }
    contradictions: list[dict[str, Any]] = []

    allergy_events = [event for event in events if event.type == "allergy_record"]
    allergy_contradictions = [
        event
        for event in events
        if event.type == "nursing_note"
        and (
            "no known drug allergies" in (event.body_text or "").lower()
            or (event.payload or {}).get("assertion") == "no_known_allergies"
        )
    ]
    if allergy_events and allergy_contradictions:
        contradictions.append(
            {
                "id": "contradiction_allergy",
                "kind": "clinical_record",
                "title": "Allergy record contradicts a nursing note",
                "explanation": (
                    "A penicillin allergy is documented in the record, while a nursing admission note "
                    "asserts no known drug allergies. The claim pack must not present these as compatible."
                ),
                "evidence_event_ids": [allergy_events[0].id, allergy_contradictions[0].id],
            }
        )

    active_meds = {str(item.get("drug", "")).lower(): item for item in state.get("active_meds", [])}
    for event in events:
        for action in (event.payload or {}).get("plan_actions", []) or []:
            if not isinstance(action, dict) or action.get("status") != "open":
                continue
            drug = str(action.get("drug", "")).lower()
            if action.get("action") == "hold" and drug in active_meds:
                contradictions.append(
                    {
                        "id": f"contradiction_plan_{drug}",
                        "kind": "medication",
                        "title": f"Open plan action conflicts with the active {action.get('drug')} order",
                        "explanation": (
                            f"The documented plan says hold {action.get('drug')}, but it remains active "
                            "in the inpatient medication list with no documented resolution."
                        ),
                        "evidence_event_ids": [event.id, active_meds[drug].get("event_id")],
                    }
                )
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


def leakage(db: Session, patient: Patient, encounter: Encounter, state: dict[str, Any]) -> dict[str, Any]:
    prep = claim_prep(db, patient, encounter, state)
    findings = []
    for item in prep["unbilled_procedures"]:
        findings.append(
            {
                "id": f"leak_{item['event_id']}",
                "procedure": item["procedure"],
                "billing_status": "unbilled",
                "explanation": "Documented procedure is absent from the seeded bill.",
                "evidence_event_ids": item["evidence_event_ids"],
            }
        )
    for item in prep.get("underbilled_items", []):
        findings.append(
            {
                "id": f"underbilled_{item['id']}",
                "procedure": item["description"],
                "billing_status": "underbilled",
                "explanation": (
                    f"Seeded expected amount INR {item['expected_amount']:,.0f} exceeds the billed "
                    f"INR {item['billed_amount']:,.0f} by INR {item['variance']:,.0f}."
                ),
                "evidence_event_ids": item["evidence_event_ids"],
            }
        )
    for item in prep["unsupported_items"]:
        findings.append(
            {
                "id": f"unsupported_{item['id']}",
                "procedure": item["description"],
                "billing_status": "unsupported",
                "explanation": "Billed item has no supporting documentation event.",
                "evidence_event_ids": item["evidence_event_ids"],
            }
        )
    return {
        "findings": findings,
        "count": len(findings),
        "summary": f"{len(findings)} documentation-to-billing gaps found by deterministic comparison.",
    }


def claim_pack_html(patient: Patient, encounter: Encounter, prep: dict[str, Any]) -> str:
    def rows(items: list[dict[str, Any]], label_key: str, value_key: str) -> str:
        if not items:
            return '<tr><td colspan="2" class="muted">None</td></tr>'
        return "".join(
            f"<tr><td>{escape(str(item.get(label_key, '')))}</td>"
            f"<td>{escape(str(item.get(value_key, '')))}</td></tr>"
            for item in items
        )

    doc_rows = "".join(
        f"<tr><td>{escape(item['label'])}</td>"
        f"<td class='{ 'ok' if item['present'] else 'bad' }'>"
        f"{'Present' if item['present'] else 'MISSING'}</td></tr>"
        for item in prep["required_documents"]
    )
    contradiction_rows = "".join(
        f"<tr><td>{escape(str(item.get('title', '')))}</td>"
        f"<td class='bad'>{escape(str(item.get('explanation', '')))}</td></tr>"
        for item in prep.get("contradictions", [])
    ) or '<tr><td colspan="2" class="muted">No contradictions found</td></tr>'
    underbilled_rows = "".join(
        f"<tr><td>{escape(str(item['description']))}</td>"
        f"<td>{item['billed_amount']:,.0f}</td><td>{item['expected_amount']:,.0f}</td></tr>"
        for item in prep.get("underbilled_items", [])
    ) or '<tr><td colspan="3" class="muted">No underbilled items</td></tr>'
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
  <div class="meta">TPA review status: {escape(str(prep.get('tpa_review', {}).get('status', 'unknown')))} · contradictions: {len(prep.get('contradictions', []))}</div>
  <h2>Contradictions before submission</h2>
  <table><thead><tr><th>Issue</th><th>Explanation</th></tr></thead><tbody>{contradiction_rows}</tbody></table>
  <h2>Required documents</h2>
  <table><thead><tr><th>Document</th><th>Status</th></tr></thead><tbody>{doc_rows}</tbody></table>
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
  <h2>Documentation gaps</h2>
  <table><thead><tr><th>Item</th><th>Gap</th></tr></thead><tbody>
    {''.join(
        f"<tr><td>{escape(str(item['procedure']))}</td><td class='bad'>Documented, not billed</td></tr>"
        for item in prep['unbilled_procedures']
    ) or '<tr><td colspan="2" class="muted">No unbilled procedures</td></tr>'}
    {''.join(
        f"<tr><td>{escape(str(item['description']))}</td><td class='bad'>Billed, no supporting documentation</td></tr>"
        for item in prep['unsupported_items']
    )}
    {''.join(
        f"<tr><td>{escape(str(item['description']))}</td><td class='bad'>Underbilled: {item['variance']:,.0f} below expected</td></tr>"
        for item in prep.get('underbilled_items', [])
    )}
  </tbody></table>
  <p class="muted">Generated by the MediBytes ARD demo. Synthetic data. No claim was submitted.</p>
</body></html>"""
