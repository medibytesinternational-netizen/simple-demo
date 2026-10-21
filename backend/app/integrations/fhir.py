"""FHIR R4 mappers: pure functions from a Bundle to timeline-event descriptions.

Nothing here touches the database or the network. ``bundle_to_events`` returns what *would* be
written; ``ingest.py`` decides what is new. Nothing is invented: a field the source did not send is
left empty (a lab flag with no interpretation is ``unknown``, not guessed from the range).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FLAGS = {"H": "high", "L": "low", "N": "normal", "HH": "critical", "LL": "critical"}
STOPPED = {"stopped", "completed", "cancelled"}
NOT_ACTIONABLE = {"draft", "entered-in-error", "unknown"}
NOT_AN_ORDER_INTENT = {"proposal", "plan"}


# ---------------------------------------------------------------- small helpers
def source_label(system: str) -> str:
    return f"fhir:{system}"


def concept_text(concept: Any) -> str:
    """Readable text of a CodeableConcept (text, else coding display, else coding code)."""
    if not isinstance(concept, dict):
        return ""
    if concept.get("text"):
        return str(concept["text"]).strip()
    for coding in concept.get("coding") or []:
        if coding.get("display"):
            return str(coding["display"]).strip()
        if coding.get("code"):
            return str(coding["code"]).strip()
    return ""


def parse_time(value: Any) -> datetime | None:
    """ISO 8601 to naive UTC (the app stores naive times). None when it cannot be read."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def number_text(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _ref(resource: dict[str, Any]) -> str:
    return f"{resource.get('resourceType', '?')}/{resource.get('id', '?')}"


def _categories(resource: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    for category in resource.get("category") or []:
        for coding in category.get("coding") or []:
            if coding.get("code"):
                codes.add(str(coding["code"]).lower())
        if category.get("text"):
            codes.add(str(category["text"]).lower())
    return codes


def _flag(resource: dict[str, Any]) -> str:
    for interpretation in resource.get("interpretation") or []:
        for coding in interpretation.get("coding") or []:
            code = str(coding.get("code", "")).upper()
            if code in FLAGS:
                return FLAGS[code]
    return "unknown"


def _quantity_text(quantity: Any) -> str:
    if not isinstance(quantity, dict) or quantity.get("value") is None:
        return ""
    unit = quantity.get("unit") or quantity.get("code") or ""
    return f"{number_text(quantity['value'])} {unit}".strip()


def _reference_range(resource: dict[str, Any]) -> str:
    ranges = resource.get("referenceRange") or []
    if not ranges:
        return ""
    first = ranges[0]
    if first.get("text"):
        return str(first["text"])
    low = (first.get("low") or {}).get("value")
    high = (first.get("high") or {}).get("value")
    if low is not None and high is not None:
        return f"{number_text(low)} - {number_text(high)}"
    if low is not None:
        return f"> {number_text(low)}"
    if high is not None:
        return f"< {number_text(high)}"
    return ""


def _observation_time(resource: dict[str, Any]) -> datetime | None:
    return (
        parse_time(resource.get("effectiveDateTime"))
        or parse_time((resource.get("effectivePeriod") or {}).get("start"))
        or parse_time(resource.get("effectiveInstant"))
        or parse_time(resource.get("issued"))
    )


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


# ---------------------------------------------------------------- patients
def patient_mrn(patient: dict[str, Any]) -> str:
    identifiers = patient.get("identifier") or []
    for identifier in identifiers:
        codes = {str(c.get("code", "")).upper() for c in (identifier.get("type") or {}).get("coding", [])}
        if "MR" in codes and identifier.get("value"):
            return str(identifier["value"])
    for identifier in identifiers:
        if "mrn" in str(identifier.get("system", "")).lower() and identifier.get("value"):
            return str(identifier["value"])
    for identifier in identifiers:
        if identifier.get("value"):
            return str(identifier["value"])
    return ""


def _patient_index(bundle: dict[str, Any]) -> dict[str, str]:
    """Every way a resource may point at a bundled Patient, mapped to its MRN."""
    index: dict[str, str] = {}
    for entry in bundle.get("entry") or []:
        resource = entry.get("resource") or {}
        if resource.get("resourceType") != "Patient":
            continue
        mrn = patient_mrn(resource)
        if resource.get("id"):
            index[f"Patient/{resource['id']}"] = mrn
        if entry.get("fullUrl"):
            index[str(entry["fullUrl"])] = mrn
    return index


def _subject_mrn(resource: dict[str, Any], index: dict[str, str], fallback: str | None) -> str:
    subject = resource.get("subject") or resource.get("patient") or {}
    reference = str(subject.get("reference", ""))
    if reference:
        if reference in index:
            return index[reference]
        tail = "/".join(reference.rstrip("/").split("/")[-2:])
        if tail in index:
            return index[tail]
    identifier = subject.get("identifier") or {}
    if identifier.get("value"):
        return str(identifier["value"])
    if not reference and fallback:
        return fallback
    if reference and fallback and not index:
        return fallback
    return ""


# ---------------------------------------------------------------- resource mappers
# Each returns (item, None) or (None, reason). An item is a dict:
#   type, title, body_text, payload, occurred_at, effects ({"allergy": str, "problem": str})
def _lab(resource: dict[str, Any], system: str) -> tuple[dict[str, Any] | None, str | None]:
    name = concept_text(resource.get("code"))
    if not name:
        return None, "observation has no name"
    quantity = resource.get("valueQuantity")
    if isinstance(quantity, dict) and quantity.get("value") is not None:
        value: Any = quantity["value"]
        unit = quantity.get("unit") or quantity.get("code") or ""
    elif resource.get("valueString") not in (None, ""):
        value, unit = resource["valueString"], ""
    elif resource.get("valueInteger") is not None:
        value, unit = resource["valueInteger"], ""
    elif resource.get("valueCodeableConcept"):
        value, unit = concept_text(resource["valueCodeableConcept"]), ""
    else:
        return None, "observation has no result value"
    collected = _observation_time(resource)
    reference_range = _reference_range(resource)
    flag = _flag(resource)
    shown = f"{number_text(value)} {unit}".strip()
    return {
        "type": "lab_result",
        "title": f"{name} — {shown}",
        "body_text": f"{name}: {shown}"
        + (f" (reference {reference_range})" if reference_range else "")
        + f", flag {flag}. Received from {system} by FHIR.",
        "payload": {
            "name": name,
            "value": value,
            "unit": unit,
            "reference_range": reference_range,
            "flag": flag,
            "collected_at": _iso(collected),
            "review_status": "unreviewed",
        },
        "occurred_at": collected,
    }, None


def _vital(resource: dict[str, Any], system: str) -> tuple[dict[str, Any] | None, str | None]:
    label = concept_text(resource.get("code"))
    if not label:
        return None, "observation has no name"
    unit = ""
    if isinstance(resource.get("valueQuantity"), dict) and resource["valueQuantity"].get("value") is not None:
        quantity = resource["valueQuantity"]
        value = number_text(quantity["value"])
        unit = quantity.get("unit") or quantity.get("code") or ""
    elif resource.get("component"):
        parts = []
        for component in resource["component"]:
            quantity = component.get("valueQuantity") or {}
            if quantity.get("value") is None:
                continue
            parts.append(number_text(quantity["value"]))
            unit = unit or quantity.get("unit") or quantity.get("code") or ""
        if not parts:
            return None, "observation has no result value"
        value = "/".join(parts)
    elif resource.get("valueString") not in (None, ""):
        value = str(resource["valueString"])
    else:
        return None, "observation has no result value"
    recorded = _observation_time(resource)
    device = (resource.get("device") or {}).get("display") or f"FHIR {system}"
    shown = f"{value} {unit}".strip()
    return {
        "type": "device_reading",
        "title": f"{label} — {shown}",
        "body_text": f"{label}: {shown} from {device}.",
        "payload": {
            "category": "vitals",
            "label": label,
            "value": value,
            "unit": unit,
            "recorded_at": _iso(recorded),
            "device": device,
            "flag": _flag(resource),
        },
        "occurred_at": recorded,
    }, None


def _observation(resource, system):
    categories = _categories(resource)
    if "laboratory" in categories:
        return _lab(resource, system)
    if "vital-signs" in categories:
        return _vital(resource, system)
    return None, "unsupported observation category"


def _frequency(timing: dict[str, Any]) -> str:
    text = concept_text(timing.get("code"))
    if text:
        return text
    repeat = timing.get("repeat") or {}
    count, period, unit = repeat.get("frequency"), repeat.get("period"), repeat.get("periodUnit")
    names = {"s": "second", "min": "minute", "h": "hour", "d": "day", "wk": "week", "mo": "month"}
    if count and period and unit:
        unit_name = names.get(unit, unit)
        if float(period) == 1:
            return f"{number_text(count)} per {unit_name}"
        return f"{number_text(count)} per {number_text(period)} {unit_name}s"
    return ""


def _medication_name(resource: dict[str, Any]) -> str:
    name = concept_text(resource.get("medicationCodeableConcept"))
    if name:
        return name
    reference = str((resource.get("medicationReference") or {}).get("reference", ""))
    if reference.startswith("#"):
        for contained in resource.get("contained") or []:
            if contained.get("id") == reference[1:]:
                return concept_text(contained.get("code"))
    return ""


def _medication(resource: dict[str, Any], system: str) -> tuple[dict[str, Any] | None, str | None]:
    status = str(resource.get("status", "")).lower()
    if status in NOT_ACTIONABLE or status not in {"active", "on-hold"} | STOPPED:
        return None, f"medication request status '{status or 'missing'}' is not an order"
    intent = str(resource.get("intent", "")).lower()
    if intent in NOT_AN_ORDER_INTENT:
        return None, f"medication request intent '{intent}' is not an order"
    drug = _medication_name(resource)
    if not drug:
        return None, "medication could not be read from the request"
    dosage = (resource.get("dosageInstruction") or [{}])[0]
    rate = (dosage.get("doseAndRate") or [{}])[0]
    dose = _quantity_text(rate.get("doseQuantity"))
    route = concept_text(dosage.get("route"))
    frequency = _frequency(dosage.get("timing") or {})
    reasons = resource.get("reasonCode") or []
    indication = concept_text(reasons[0]) if reasons else ""
    if not indication:
        refs = resource.get("reasonReference") or []
        indication = str(refs[0].get("display", "")) if refs else ""
    mapped = "stopped" if status in STOPPED else ("on_hold" if status == "on-hold" else "active")
    payload = {
        "drug": drug,
        "kind": "inpatient",
        "status": mapped,
        "dose": dose,
        "route": route,
        "frequency": frequency,
        "indication": indication,
    }
    if dosage.get("text"):
        payload["instruction"] = str(dosage["text"])
    details = " ".join(part for part in (dose, route, frequency) if part)
    word = {"active": "ordered", "stopped": "stopped", "on_hold": "on hold"}[mapped]
    return {
        "type": "med_order",
        "title": f"{drug} {word}",
        "body_text": f"{drug} {details}".strip()
        + (f" for {indication}" if indication else "")
        + f". Status {mapped}. Received from {system} by FHIR.",
        "payload": payload,
        "occurred_at": parse_time(resource.get("authoredOn")),
    }, None


def _allergy(resource: dict[str, Any], system: str) -> tuple[dict[str, Any] | None, str | None]:
    verification = concept_text(resource.get("verificationStatus")).lower()
    if "entered-in-error" in verification:
        return None, "allergy was entered in error"
    substance = concept_text(resource.get("code"))
    if not substance:
        return None, "allergy has no substance"
    reaction = ""
    for item in resource.get("reaction") or []:
        for manifestation in item.get("manifestation") or []:
            reaction = concept_text(manifestation)
            if reaction:
                break
        if reaction:
            break
    entry = f"{substance} — {reaction}" if reaction else substance
    return {
        "type": "allergy_record",
        "title": f"Allergy record — {substance}",
        "body_text": f"{entry} (received from {system} by FHIR). Verify before prescribing.",
        "payload": {
            "substance": substance,
            "reaction": reaction,
            "verified": False,
            "criticality": resource.get("criticality", ""),
            "clinical_status": concept_text(resource.get("clinicalStatus")),
        },
        "occurred_at": parse_time(resource.get("recordedDate")) or parse_time(resource.get("onsetDateTime")),
        "effects": {"allergy": entry},
    }, None


def _condition(resource: dict[str, Any], system: str) -> tuple[dict[str, Any] | None, str | None]:
    if "entered-in-error" in concept_text(resource.get("verificationStatus")).lower():
        return None, "condition was entered in error"
    if concept_text(resource.get("clinicalStatus")).lower() in {"inactive", "resolved", "remission"}:
        return None, "condition is not active"
    problem = concept_text(resource.get("code"))
    if not problem:
        return None, "condition has no name"
    return {"type": None, "title": problem, "body_text": "", "payload": {}, "occurred_at": None,
            "effects": {"problem": problem}}, None


MAPPERS = {
    "Observation": _observation,
    "MedicationRequest": _medication,
    "AllergyIntolerance": _allergy,
    "Condition": _condition,
}


# ---------------------------------------------------------------- bundle
def bundle_to_events(bundle: dict[str, Any], system: str, mrn: str | None = None) -> dict[str, Any]:
    """Describe what a Bundle holds.

    Returns {"items": [...], "skipped": [{"resource", "reason"}], "errors": [...], "patients": [{"id","mrn"}]}.
    ``mrn`` is used only for a resource that names no patient at all and a bundle with no Patient.
    """
    index = _patient_index(bundle)
    items: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    patients: list[dict[str, str]] = []
    for entry in bundle.get("entry") or []:
        resource = entry.get("resource")
        if not isinstance(resource, dict):
            errors.append({"resource": "?", "reason": "entry has no resource"})
            continue
        kind = resource.get("resourceType", "?")
        label = _ref(resource)
        if kind == "Patient":
            patients.append({"id": str(resource.get("id", "")), "mrn": patient_mrn(resource)})
            continue
        mapper = MAPPERS.get(kind)
        if mapper is None:
            skipped.append({"resource": label, "reason": f"unsupported resource type {kind}"})
            continue
        if not resource.get("id"):
            errors.append({"resource": label, "reason": "resource has no id"})
            continue
        patient_key = _subject_mrn(resource, index, mrn)
        if not patient_key:
            errors.append({"resource": label, "reason": "resource names no patient"})
            continue
        item, reason = mapper(resource, system)
        if item is None:
            skipped.append({"resource": label, "reason": reason or "not mapped"})
            continue
        item.setdefault("effects", {})
        version = (resource.get("meta") or {}).get("versionId")
        item.update(
            {
                "resource": label,
                "resource_type": kind,
                "mrn": patient_key,
                "source": source_label(system),
                "external_id": f"{system}:{kind}/{resource['id']}",
                "version": str(version) if version is not None else None,
            }
        )
        if item["type"]:
            item["payload"]["external_id"] = item["external_id"]
            item["payload"]["external_version"] = item["version"]
        items.append(item)
    return {"items": items, "skipped": skipped, "errors": errors, "patients": patients}
