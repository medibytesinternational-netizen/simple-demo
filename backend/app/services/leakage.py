"""F13 revenue-leakage detection: documented services compared with charges.

Documented services come from approved timeline events (procedures, medicines given, approved
investigation requests, specialist consults) and from the encounter dates (bed-days). Each service
is mapped to a tariff code through the maps below and matched to bill lines by ``code``, never by
the words in a description. Amounts are computed from the tariff table, never typed per bill row.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..models import BillLineItem, Encounter, Patient
from ..models_ext.f13_tariff import TariffItem
from ..seeds.f13_tariff import upsert_tariff
from .timeline import list_events

# --- Documented service-to-code maps ------------------------------------------------------------
# An event payload may carry its own tariff ``code``; otherwise these maps decide. Keys are lower case.
PROCEDURE_CODES: dict[str, str] = {
    "wound debridement": "97597",
    "physiotherapy": "PT01",
    "physiotherapy session": "PT01",
}
# (first word of the drug name, route) -> code. Only IV antibiotics are charged separately;
# other medicines are bundled in the room charge and are listed as unmapped, not flagged.
MEDICATION_CODES: dict[tuple[str, str], str] = {
    (drug, "IV"): "J01"
    for drug in ("flucloxacillin", "ceftriaxone", "meropenem", "vancomycin", "piperacillin", "cefazolin")
}
STUDY_CODES: dict[str, str] = {
    "renal ultrasound": "US-RENAL",
    "renal ultrasound with doppler": "US-RENAL",
}
REQUEST_TYPE_CODES: dict[str, str] = {"laboratory": "LAB01", "imaging": "IMG01"}
CONSULT_CODES: dict[str, str] = {"nephrology": "CONS-NEPH"}
DEFAULT_CONSULT_CODE = "CONS01"
BED_DAY_CODES: dict[str, str] = {"ICU": "ICU01"}
DEFAULT_BED_DAY_CODE = "ROOM2"

AS_PHRASE = {
    "procedure": "as performed",
    "medication": "as given",
    "investigation": "as ordered (not confirmed as performed)",
    "consult": "with a recorded specialist response",
    "bed_day": "as whole bed-days",
}


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _code(value: Any) -> str:
    return str(value or "").strip().upper()


def _inr(value: float) -> str:
    return f"INR {value:,.0f}"


def _dedupe(ids: list[str | None]) -> list[str]:
    seen: list[str] = []
    for item in ids:
        if item and item not in seen:
            seen.append(item)
    return seen


def _tariff(db: Session) -> dict[str, TariffItem]:
    rows = list(db.scalars(select(TariffItem)))
    if not rows:  # a database that never ran the seed hook
        upsert_tariff(db)
        db.commit()
        rows = list(db.scalars(select(TariffItem)))
    return {_code(row.code): row for row in rows}


class _Documented:
    def __init__(self, code: str, kind: str, label: str) -> None:
        self.code = code
        self.kind = kind
        self.label = label
        self.documented_as = AS_PHRASE[kind]
        self.quantity = 0
        self.event_ids: list[str] = []
        self.refs: list[dict[str, str]] = []


def _documented_services(
    encounter: Encounter, events: list[Any]
) -> tuple[dict[str, _Documented], list[dict[str, Any]]]:
    found: dict[str, _Documented] = {}
    unmapped: list[dict[str, Any]] = []

    def add(code: str, kind: str, label: str, event_ids: list[str],
            refs: list[dict[str, str]] | None = None, quantity: int = 1) -> None:
        item = found.setdefault(code, _Documented(code, kind, label))
        item.quantity += quantity
        item.event_ids.extend(event_ids)
        item.refs.extend(refs or [])

    for event in events:
        payload = event.payload or {}
        explicit = _code(payload.get("code"))
        if event.type == "procedure":
            name = payload.get("procedure") or event.title
            code = explicit or _code(PROCEDURE_CODES.get(_norm(name)))
            if code:
                add(code, "procedure", str(name), [event.id])
            else:
                unmapped.append({"label": str(name), "kind": "procedure", "evidence_event_ids": [event.id]})
        elif event.type == "medication_administration":
            if _norm(payload.get("status")) != "given":
                continue  # held, refused or unknown: nothing was given, so nothing to charge
            drug = str(payload.get("drug") or event.title)
            first = _norm(drug).split(" ")[0]
            route = str(payload.get("route") or "").strip().upper()
            code = explicit or _code(MEDICATION_CODES.get((first, route)))
            if code:
                add(code, "medication", drug, [event.id])
            else:
                unmapped.append({"label": drug, "kind": "medication", "evidence_event_ids": [event.id]})
        elif event.type == "investigation_request":
            study = payload.get("study") or event.title
            code = explicit or _code(
                STUDY_CODES.get(_norm(study)) or REQUEST_TYPE_CODES.get(_norm(payload.get("request_type")))
            )
            if code:
                add(code, "investigation", str(study), [event.id])
            else:
                unmapped.append({"label": str(study), "kind": "investigation", "evidence_event_ids": [event.id]})
        elif event.type == "referral_consult":
            label = f"{event.subtype or 'Specialist'} consult"
            code = explicit or _code(CONSULT_CODES.get(_norm(event.subtype), DEFAULT_CONSULT_CODE))
            add(code, "consult", label, [event.id])

    if encounter.admitted_at:
        end = encounter.discharged_at or clock.now()
        days = max(0, int((end - encounter.admitted_at).total_seconds() // 86400))
        if days:
            code = BED_DAY_CODES.get(str(encounter.kind or "").upper(), DEFAULT_BED_DAY_CODE)
            evidence = [e.id for e in events if e.type in {"admission_note", "discharge_summary"}]
            add(code, "bed_day", "Bed-days", evidence, [{"kind": "encounter", "id": encounter.id}], quantity=days)
    for item in found.values():
        item.event_ids = _dedupe(item.event_ids)
    return found, unmapped


def leakage(db: Session, patient: Patient, encounter: Encounter, state: dict[str, Any]) -> dict[str, Any]:
    all_events = list_events(db, patient.id, encounter.id, approved_only=True, limit=1000)
    replaced = {e.supersedes_event_id for e in all_events if e.supersedes_event_id}
    events = [e for e in all_events if e.status == "approved" and e.id not in replaced]
    bill_event = next((e for e in events if e.type == "billing"), None)
    bill_event_ids = [bill_event.id] if bill_event else []

    tariff = _tariff(db)
    documented, unmapped = _documented_services(encounter, events)
    lines = list(
        db.scalars(
            select(BillLineItem)
            .where(BillLineItem.patient_id == patient.id, BillLineItem.encounter_id == encounter.id)
            .order_by(BillLineItem.billed_at)
        )
    )
    by_code: dict[str, list[BillLineItem]] = {}
    for line in lines:
        by_code.setdefault(_code(line.code), []).append(line)

    first_pass: list[dict[str, Any]] = []  # unbilled and quantity mismatches
    under_pass: list[dict[str, Any]] = []
    unsupported_pass: list[dict[str, Any]] = []

    for code, service in documented.items():
        row = tariff.get(code)
        price = row.unit_price if row else None
        qty = service.quantity
        expected = price * qty if price is not None else None
        group = by_code.get(code, [])
        priced = f"{qty} x {_inr(price)} = {_inr(expected)}" if price is not None else "no tariff price on file"
        common = {
            "procedure": service.label,
            "code": code,
            "service_kind": service.kind,
            "unit_price": price,
            "documented_quantity": qty,
            "expected_amount": expected,
            "documented_as": service.documented_as,
        }
        if not group:
            event_id = service.event_ids[0] if len(service.event_ids) == 1 and service.kind != "bed_day" else None
            first_pass.append({
                **common,
                "id": f"leak_{event_id or code}",
                "kind": "unbilled",
                "billing_status": "unbilled",
                "billed_quantity": 0,
                "billed_amount": 0,
                "variance": expected,
                "explanation": (
                    f"{service.label} (code {code}) is documented {service.documented_as} "
                    f"but no bill line carries code {code}. Tariff value: {priced}."
                ),
                "evidence_event_ids": service.event_ids,
                "evidence_refs": service.refs,
            })
            continue
        if row is None or not price:
            continue
        billed = sum(float(line.amount or 0) for line in group)
        ratio = billed / price
        billed_qty = round(ratio) if round(ratio) >= 1 and abs(ratio - round(ratio)) < 0.001 else None
        evidence = _dedupe(
            service.event_ids + [i for line in group for i in (line.documentation_event_ids or [])] + bill_event_ids
        )
        if billed_qty is not None and billed_qty != qty:
            short = billed_qty < qty
            first_pass.append({
                **common,
                "id": f"quantity_{group[0].id}",
                "kind": "quantity_mismatch",
                "billing_status": "underbilled" if short else "unsupported",
                "billed_quantity": billed_qty,
                "billed_amount": billed,
                "variance": (qty - billed_qty) * price,
                "explanation": (
                    f"Quantity mismatch for {service.label} (code {code}): {qty} documented "
                    f"{service.documented_as}, {billed_qty} billed. Tariff {_inr(price)} each, "
                    f"so the bill is {_inr(abs(qty - billed_qty) * price)} "
                    f"{'below' if short else 'above'} the documented quantity."
                ),
                "evidence_event_ids": evidence,
                "evidence_refs": service.refs,
            })
        elif billed_qty is None and billed + 0.005 < expected:
            under_pass.append({
                **common,
                "id": f"underbilled_{group[0].id}",
                "kind": "underbilled",
                "billing_status": "underbilled",
                "billed_quantity": None,
                "billed_amount": billed,
                "variance": round(expected - billed, 2),
                "explanation": (
                    f"Billed {_inr(billed)} for {service.label} (code {code}) is below the tariff value "
                    f"{priced}, a shortfall of {_inr(expected - billed)}."
                ),
                "evidence_event_ids": evidence,
                "evidence_refs": service.refs,
            })

    for code, group in by_code.items():
        row = tariff.get(code)
        if code in documented or row is None or not row.unit_price:
            continue
        billed = sum(float(line.amount or 0) for line in group)
        if billed + 0.005 < row.unit_price:
            line = group[0]
            label = line.description or row.description
            under_pass.append({
                "id": f"underbilled_{line.id}",
                "procedure": label,
                "code": code,
                "service_kind": row.kind,
                "kind": "underbilled",
                "billing_status": "underbilled",
                "unit_price": row.unit_price,
                "documented_quantity": None,
                "billed_quantity": None,
                "billed_amount": billed,
                "expected_amount": row.unit_price,
                "variance": round(row.unit_price - billed, 2),
                "documented_as": None,
                "explanation": (
                    f"Billed {_inr(billed)} for {label} (code {code}) is below the tariff price "
                    f"{_inr(row.unit_price)}, a shortfall of {_inr(row.unit_price - billed)}."
                ),
                "evidence_event_ids": _dedupe(
                    [i for item in group for i in (item.documentation_event_ids or [])] + bill_event_ids
                ),
                "evidence_refs": [{"kind": "bill_line", "id": item.id} for item in group],
            })

    for line in lines:
        if line.documentation_event_ids:
            continue
        code = _code(line.code)
        row = tariff.get(code)
        amount = float(line.amount or 0)
        unsupported_pass.append({
            "id": f"unsupported_{line.id}",
            "procedure": line.description,
            "code": code,
            "service_kind": row.kind if row else None,
            "kind": "unsupported",
            "billing_status": "unsupported",
            "unit_price": row.unit_price if row else None,
            "documented_quantity": None,
            "billed_quantity": None,
            "billed_amount": amount,
            "expected_amount": None,
            "variance": None,
            "documented_as": None,
            "explanation": (
                f"Billed item {line.description} (code {code}, {_inr(amount)}) "
                "has no supporting documentation event."
            ),
            "evidence_event_ids": bill_event_ids,
            "evidence_refs": [{"kind": "bill_line", "id": line.id}],
        })

    findings = first_pass + under_pass + unsupported_pass
    at_risk = sum(
        item["variance"] for item in findings
        if item["billing_status"] in {"unbilled", "underbilled"} and item.get("variance")
    )
    return {
        "findings": findings,
        "count": len(findings),
        "summary": (
            f"{len(findings)} documentation-to-billing gaps found by comparing documented services with "
            "the bill by tariff code."
        ),
        "leakage_amount": round(float(at_risk), 2),
        "unmapped_services": unmapped,
    }
