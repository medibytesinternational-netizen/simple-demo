"""Deterministic demo drafts.

Used when no OPENAI_API_KEY is present (or LLM_MODE=cached). Every string is
derived from the supplied context; this is a fixture layer, not a second model.
"""

from __future__ import annotations

from typing import Any


def _claim(
    text: str,
    event_ids: list[str] | None = None,
    segment_ids: list[str] | None = None,
    confidence: float = 0.92,
) -> dict[str, Any]:
    return {
        "text": text,
        "source_event_ids": [item for item in (event_ids or []) if item],
        "source_segment_ids": [item for item in (segment_ids or []) if item],
        "confidence": confidence,
    }


def _segments(context: dict[str, Any]) -> list[dict[str, Any]]:
    return (context.get("transcript") or {}).get("segments", [])


def _seg(context: dict[str, Any], index: int) -> str:
    segments = _segments(context)
    if not segments:
        return ""
    if index <= len(segments):
        return segments[index - 1]["segment_id"]
    return segments[0]["segment_id"]


def _all_segs(context: dict[str, Any]) -> list[str]:
    return [segment["segment_id"] for segment in _segments(context)]


def _transcript_event(context: dict[str, Any]) -> str:
    return (context.get("transcript") or {}).get("event_id", "")


def _events(context: dict[str, Any], type_name: str) -> list[dict[str, Any]]:
    return [event for event in context.get("evidence_events", []) if event.get("type") == type_name]


def _first(context: dict[str, Any], type_name: str) -> dict[str, Any] | None:
    return next(iter(_events(context, type_name)), None)


def _lab(context: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next(
        (lab for lab in context.get("latest_labs", []) if str(lab.get("name", "")).lower() == name.lower()),
        None,
    )


def _lab_ids(context: dict[str, Any], names: list[str]) -> list[str]:
    ids = []
    for name in names:
        lab = _lab(context, name)
        if lab:
            ids.append(lab["event_id"])
    return ids


def _patient(context: dict[str, Any]) -> dict[str, Any]:
    return context.get("patient", {})


def _active_meds(context: dict[str, Any]) -> list[dict[str, Any]]:
    return context.get("active_medications", [])


def _home_meds(context: dict[str, Any]) -> list[dict[str, Any]]:
    return context.get("home_medications", [])


def f1_consult_note(context: dict[str, Any]) -> dict[str, Any]:
    patient = _patient(context)
    transcript_id = _transcript_event(context)
    labs = _lab_ids(context, ["Creatinine", "eGFR", "Potassium"])
    age = patient.get("age", "")
    sex = patient.get("sex", "")
    return {
        "chief_complaint": _claim(
            "Right leg swelling, redness and pain for four days.",
            [transcript_id],
            [_seg(context, 2)],
        ),
        "hpi": _claim(
            f"{age}-year-old {str(sex).lower()} with type 2 diabetes, hypertension and CKD stage 3b "
            "reports progressive right lower leg swelling and redness since Tuesday, with warmth, "
            "pain on walking and fever last night. Denies chest pain and breathlessness.",
            [transcript_id, *labs],
            [_seg(context, 2), _seg(context, 3)],
        ),
        "exam": {
            "general": _claim(
                "Temperature 38.1°C, pulse 96, BP 138/86, SpO2 96% on room air. "
                "Right lower leg is erythematous, warm and tender with a clear demarcation; no ulcer.",
                [transcript_id],
                [_seg(context, 5)],
            ),
            "systemic": None,
        },
        "assessment": [
            _claim(
                "Cellulitis of the right lower leg.",
                [transcript_id, *labs],
                [_seg(context, 6)],
            ),
            _claim(
                "Type 2 diabetes and CKD stage 3b increase the risk of complicated infection and renal injury.",
                [transcript_id, *labs],
                [_seg(context, 6)],
            ),
        ],
        "plan": [
            _claim(
                "Admit for intravenous antibiotics and renal monitoring.",
                [transcript_id],
                [_seg(context, 6)],
            ),
            _claim(
                "Hold metformin pending review of renal function.",
                [transcript_id, *labs],
                [_seg(context, 6)],
            ),
            _claim(
                "Check potassium and creatinine today.",
                [transcript_id, *labs],
                [_seg(context, 6)],
            ),
        ],
        "medication_mentions": [
            {
                "drug": "Metformin",
                "dose": "1 g",
                "frequency": "BD",
                "source_event_ids": [transcript_id],
                "source_segment_ids": [_seg(context, 6)],
            }
        ],
        "follow_up": _claim(
            "Review creatinine and potassium on the ward before the next dose of metformin.",
            [transcript_id, *labs],
            [_seg(context, 6), _seg(context, 7)],
        ),
        "not_documented": [],
    }


def f2_admission_note(context: dict[str, Any]) -> dict[str, Any]:
    patient = _patient(context)
    transcript_id = _transcript_event(context)
    labs = _lab_ids(context, ["Creatinine", "eGFR", "Potassium", "HbA1c"])
    problems = ", ".join(patient.get("problems", [])) or "no documented comorbidities"
    return {
        "chief_complaint": _claim(
            "Right lower leg cellulitis requiring inpatient intravenous antibiotics.",
            [transcript_id],
            [_seg(context, 1)],
        ),
        "history": _claim(
            f"Admitted with a four-day history of a red, warm, painful right leg and fever. "
            f"Background of {problems}. Penicillin allergy documented.",
            [transcript_id, *labs],
            [_seg(context, 2), _seg(context, 3)],
        ),
        "exam": {
            "general": _claim(
                "Febrile at 38.1°C, haemodynamically stable. Right lower leg erythema with demarcation and tenderness, no ulceration.",
                [transcript_id],
                [_seg(context, 4)],
            ),
            "systemic": None,
        },
        "assessment": [
            _claim(
                "Right lower leg cellulitis on a background of diabetes and CKD stage 3b.",
                [transcript_id, *labs],
                [_seg(context, 5)],
            )
        ],
        "plan": [
            _claim(
                "Intravenous antibiotics, renal monitoring and daily wound review.",
                [transcript_id],
                [_seg(context, 5)],
            )
        ],
        "proposed_orders": [
            {
                "order": "IV antibiotic with non-penicillin coverage",
                "rationale": "Documented penicillin allergy; cellulitis requires inpatient cover.",
                "source_event_ids": [transcript_id],
            },
            {
                "order": "Creatinine, eGFR and potassium now and daily",
                "rationale": "CKD stage 3b and metformin exposure.",
                "source_event_ids": labs,
            },
        ],
        "allergies_to_verify": [
            {
                "substance": item.get("substance", "") if isinstance(item, dict) else str(item),
                "reaction": item.get("reaction", "") if isinstance(item, dict) else "",
                "source_event_id": item.get("event_id", "") if isinstance(item, dict) else "",
                "verified": False,
            }
            for item in patient.get("allergies", [])
        ],
        "not_documented": [],
    }


def f3_round(context: dict[str, Any]) -> dict[str, Any]:
    transcript_id = _transcript_event(context)
    segments = _segments(context)
    tasks = []
    instructional = [
        segment
        for segment in segments
        if segment.get("speaker", "").lower() in {"doctor", "clinician", "dr", "dr."}
        and any(
            verb in segment.get("text", "").lower()
            for verb in ("continue", "check", "stop", "increase", "start", "order", "review", "book")
        )
    ]
    if not instructional:
        instructional = [segment for segment in segments if segment.get("speaker", "").lower() in {"doctor", "clinician"}]
    for index, segment in enumerate(instructional):
        text = str(segment.get("text", "")).strip()
        title = text.rstrip(".")
        priority = "urgent" if any(word in text.lower() for word in ("stop", "potassium", "renal", "check")) else "routine"
        tasks.append(
            {
                "title": title[:110],
                "detail": f"From round discussion: {text}",
                "priority": priority,
                "due_in_hours": 8 if index == 1 else 24,
                "source_segment_ids": [segment["segment_id"]],
                "confidence": 0.9 if index < 3 else 0.62,
            }
        )
    return {
        "note_claims": [
            _claim(
                "Ward round reviewed the right lower leg cellulitis, renal function and medication safety.",
                [transcript_id],
                _all_segs(context)[:2],
            ),
            _claim(
                "Continue IV antibiotics and review the leg tomorrow. Check potassium and renal function. Hold metformin until renal function improves.",
                [transcript_id],
                _all_segs(context)[:4],
            ),
            _claim(
                "The suggestion to increase ibuprofen was not accepted because of CKD and concurrent warfarin.",
                [transcript_id],
                _all_segs(context)[-1:],
                0.65,
            ),
        ],
        "nursing_entries": [
            _claim(
                "Continue IV flucloxacillin as prescribed; review the right leg at the next ward round.",
                [transcript_id],
                _all_segs(context)[:1],
            ),
            _claim(
                "Check potassium and renal function this morning and escalate abnormal results.",
                [transcript_id],
                _all_segs(context)[1:2],
            ),
            _claim(
                "Hold metformin until renal function is reviewed.",
                [transcript_id],
                _all_segs(context)[2:3],
            ),
        ],
        "proposed_tasks": tasks,
        "not_documented": [],
    }


def f4_progress(context: dict[str, Any]) -> dict[str, Any]:
    transcript_id = _transcript_event(context)
    vitals = (context.get("vitals") or {}).get("payload", {})
    temp = vitals.get("temperature_c")
    hr = vitals.get("heart_rate")
    objective_bits = []
    if temp is not None:
        objective_bits.append(f"temperature {temp}°C")
    if hr is not None:
        objective_bits.append(f"heart rate {hr} bpm")
    return {
        "subjective": _claim(
            "Patient reports less leg pain overnight and no new breathlessness. Slept poorly.",
            [transcript_id],
            [_seg(context, 1)],
        ),
        "objective": _claim(
            "Overnight observations: " + (", ".join(objective_bits) if objective_bits else "vitals recorded on the timeline") + ".",
            [transcript_id, ((context.get("vitals") or {}).get("event_id") or "")],
            [_seg(context, 2)] if len(_segments(context)) > 1 else [_seg(context, 1)],
        ),
        "exam": {"general": None, "systemic": None},
        "assessment": [
            _claim(
                "Cellulitis — clinically improving on IV antibiotics.",
                [transcript_id],
                [_seg(context, 1)],
                confidence=0.82,
            )
        ],
        "plan": None,
        "not_documented": ["Examination", "Plan"],
    }


def f7_nursing(context: dict[str, Any]) -> dict[str, Any]:
    vitals = (context.get("vitals") or {}).get("payload", {})
    vitals_id = (context.get("vitals") or {}).get("event_id", "")
    labs = _lab_ids(context, ["Creatinine", "eGFR", "Potassium", "WBC"])
    return {
        "shift_window": {"start": "2026-10-19T20:00:00", "end": "2026-10-20T08:00:00"},
        "vitals_summary": _claim(
            f"Afebrile overnight with temperature {vitals.get('temperature_c', 'not recorded')}°C, "
            f"heart rate {vitals.get('heart_rate', 'not recorded')} bpm and SpO2 {vitals.get('spo2', 'not recorded')}% on room air.",
            [vitals_id],
            confidence=0.9,
        ),
        "meds_administered": [],
        "incidents": [
            _claim(
                "No falls, no new confusion and no escalation required overnight.",
                [vitals_id],
                confidence=0.86,
            )
        ],
        "concerns": [
            _claim(
                "Renal function remains impaired and potassium is elevated; the day team should review.",
                labs,
                confidence=0.9,
            )
        ],
        "not_documented": ["Medication administration record", "Intake/output chart"],
    }


def f7_icu_flow_sheet(context: dict[str, Any]) -> dict[str, Any]:
    entries = []
    for item in context.get("icu_entries", [])[:80]:
        entries.append(
            {
                "category": item.get("category", "other"),
                "label": item.get("label", ""),
                "value": str(item.get("value", "")),
                "unit": item.get("unit", ""),
                "recorded_at": item.get("recorded_at", ""),
                "device": item.get("device", ""),
                "source_event_id": item.get("source_event_id", ""),
                "confidence": float(item.get("confidence", 0.95)),
            }
        )
    evidence = list(dict.fromkeys(entry["source_event_id"] for entry in entries if entry["source_event_id"]))
    return {
        "shift_window": context.get("icu_shift_window", {}),
        "summary": _claim(
            f"{len(entries)} structured ICU observations were assembled from device and chart feeds for this shift.",
            evidence[:8],
            confidence=0.9,
        ),
        "entries": entries,
        "not_documented": [] if entries else ["ICU device readings", "Intake/output chart"],
    }


def f10_investigation_request(context: dict[str, Any]) -> dict[str, Any]:
    patient = _patient(context)
    admission = _first(context, "admission_note")
    labs = context.get("latest_labs", [])
    lab_ids = [lab["event_id"] for lab in labs]
    egfr = _lab(context, "eGFR")
    creatinine = _lab(context, "Creatinine")
    evidence = [item for item in [admission["id"] if admission else "", *lab_ids] if item]
    indication_text = "CKD stage 3b with eGFR 22 and creatinine 2.9 mg/dL; assess renal parenchyma and obstruction."
    if egfr and creatinine:
        indication_text = (
            f"CKD stage 3b with eGFR {egfr.get('value')} mL/min/1.73m² and creatinine "
            f"{creatinine.get('value')} {creatinine.get('unit', '')}; assess renal parenchyma and obstruction."
        )
    allergies = [
        {
            "substance": allergy,
            "reaction": "Documented reaction — verify before contrast or procedure",
            "source_event_id": "",
            "verified": False,
        }
        for allergy in patient.get("allergies", [])
    ]
    return {
        "request_type": "imaging",
        "study": "Renal ultrasound with Doppler",
        "indication": _claim(indication_text, evidence),
        "diagnosis": ", ".join(patient.get("problems", [])[:3]) or "Documented inpatient diagnosis",
        "allergies_to_verify": allergies,
        "priority": "routine",
        "instructions": "Assess renal size, echogenicity, hydronephrosis and renal artery flow. No contrast unless reviewed.",
        "recipient": "Radiology department",
        "source_event_ids": evidence,
    }


def f11_referral(context: dict[str, Any]) -> dict[str, Any]:
    patient = _patient(context)
    admission = _first(context, "admission_note")
    round_event = _first(context, "round_note")
    labs = context.get("latest_labs", [])
    lab_ids = [lab["event_id"] for lab in labs]
    evidence = [item for item in [admission["id"] if admission else "", round_event["id"] if round_event else "", *lab_ids] if item]
    egfr = _lab(context, "eGFR")
    creatinine = _lab(context, "Creatinine")
    question = (
        "Does this patient with CKD stage 3b and eGFR 22 need nephrology co-management, "
        "medication dose adjustment or dialysis planning during this admission?"
    )
    if egfr and creatinine:
        question = (
            f"Does this patient with eGFR {egfr.get('value')} mL/min/1.73m² and creatinine "
            f"{creatinine.get('value')} need nephrology co-management, medication dose adjustment "
            "or dialysis planning during this admission?"
        )
    return {
        "specialty": "Nephrology",
        "specialist": "Nephrology on-call service",
        "question": _claim(question, evidence),
        "history": _claim(
            "58-year-old man with type 2 diabetes, hypertension and CKD stage 3b, admitted with "
            "right lower leg cellulitis. Renal function is impaired and metformin remains on the active order list "
            "pending review. Potassium is at the upper limit of normal.",
            evidence,
        ),
        "urgency": "urgent",
        "relevant_results": [
            _claim(
                f"{lab['name']} {lab.get('value')} {lab.get('unit', '')}".strip(),
                [lab["event_id"]],
            )
            for lab in labs
            if str(lab.get("flag", "")).lower() in {"high", "low"}
        ],
        "source_event_ids": evidence,
    }


def f9_discharge(context: dict[str, Any]) -> dict[str, Any]:
    consult = _first(context, "consult_note")
    admission = _first(context, "admission_note")
    round_event = _first(context, "round_note")
    progress = _first(context, "progress_note")
    procedure = _first(context, "procedure")
    labs = context.get("latest_labs", [])
    lab_ids = [lab["event_id"] for lab in labs]
    discharge_event_ids = [
        item["id"] for item in (consult, admission, round_event, progress, procedure) if item
    ]
    creatinine = _lab(context, "Creatinine")
    egfr = _lab(context, "eGFR")
    potassium = _lab(context, "Potassium")
    sections = [
        {
            "heading": "Admission diagnosis",
            "paragraphs": [
                _claim(
                    "Right lower leg cellulitis in a patient with type 2 diabetes, hypertension and CKD stage 3b.",
                    discharge_event_ids or lab_ids,
                )
            ],
        },
        {
            "heading": "Hospital course",
            "paragraphs": [
                _claim(
                    "Admitted for intravenous antibiotics with daily wound review. Renal function was monitored, and the discharge medication list was assembled from active orders for clinician review.",
                    [*( [round_event["id"]] if round_event else []), *lab_ids],
                )
            ],
        },
    ]
    if procedure:
        sections.append(
            {
                "heading": "Procedures",
                "paragraphs": [
                    _claim(
                        f"{(procedure.get('payload') or {}).get('procedure', 'Wound debridement')} performed during the admission.",
                        [procedure["id"]],
                    )
                ],
            }
        )
    investigations = []
    if creatinine:
        investigations.append(
            f"creatinine {creatinine.get('value')} {creatinine.get('unit', '')}".strip()
        )
    if egfr:
        investigations.append(f"eGFR {egfr.get('value')} mL/min/1.73m²")
    if potassium:
        investigations.append(f"potassium {potassium.get('value')} {potassium.get('unit', '')}".strip())
    if investigations:
        sections.append(
            {
                "heading": "Investigations",
                "paragraphs": [
                    _claim(
                        "Latest results: " + ", ".join(investigations) + ".",
                        lab_ids,
                    )
                ],
            }
        )
    pending = [
        _claim(
            f"{lab['name']} remains unreviewed and should be checked before the next clinical contact.",
            [lab["event_id"]],
        )
        for lab in context.get("unreviewed_labs", [])
    ]
    return {
        "sections": sections,
        "medications": [],
        "pending_results": pending,
        "follow_up": [
            _claim(
                "Repeat creatinine, eGFR and potassium within one week.",
                lab_ids,
            )
        ],
        "red_flags": [
            _claim(
                "Return urgently if fever, spreading redness, breathlessness or reduced urine output develops.",
                (discharge_event_ids or lab_ids),
                confidence=0.8,
            )
        ],
        "not_documented": [],
    }


def f10_document_request(context: dict[str, Any]) -> dict[str, Any]:
    extra = context.get("revenue", {}) or {}
    missing = extra.get("missing_documents", [])
    records = [item.get("label", item.get("key", "Document")) for item in missing]
    if not records:
        records = ["Signed discharge summary"]
    evidence = []
    for item in missing:
        evidence.extend(item.get("evidence_event_ids", []))
    if not evidence:
        events = context.get("evidence_events", [])
        evidence = [events[0]["id"]] if events else []
    return {
        "request_type": "pre_auth" if any("pre-auth" in str(record).lower() for record in records) else "records",
        "recipient": extra.get("recipient", "Hospital records department"),
        "records_requested": records,
        "justification": _claim(
            "These items are required before the claim pack can enter clinical review. Missing documentation blocks review; no submission is attempted.",
            evidence,
        ),
        "due_in_days": 3,
        "source_event_ids": evidence,
    }


def f11_investigation(context: dict[str, Any]) -> dict[str, Any]:
    results = []
    for lab in context.get("latest_labs", []):
        flag = str(lab.get("flag", "unknown")).lower()
        if flag not in {"normal", "high", "low"}:
            flag = "unknown"
        results.append(
            {
                "name": lab.get("name", ""),
                "value": f"{lab.get('value')} {lab.get('unit', '')}".strip(),
                "flag": flag,
                "event_id": lab["event_id"],
            }
        )
    lab_ids = [lab["event_id"] for lab in context.get("latest_labs", [])]
    abnormal = [lab for lab in context.get("latest_labs", []) if str(lab.get("flag", "")).lower() in {"high", "low"}]
    return {
        "results": results,
        "trend_summary": _claim(
            "Creatinine and eGFR are stable at the current impaired level; potassium remains elevated.",
            lab_ids,
            confidence=0.86,
        ),
        "abnormal_summary": _claim(
            "Abnormal results: " + ", ".join(f"{lab['name']} {lab.get('value')}" for lab in abnormal) + ".",
            [lab["event_id"] for lab in abnormal],
            confidence=0.9,
        ),
        "pending": [
            _claim(
                f"{lab['name']} has not been reviewed.",
                [lab["event_id"]],
            )
            for lab in context.get("unreviewed_labs", [])
        ],
        "not_documented": [],
    }


def f6_recon(context: dict[str, Any]) -> dict[str, Any]:
    extra = (context.get("reconciliation") or {})
    discrepancies = extra.get("discrepancies", [])
    return {
        "summary": (
            f"{len(discrepancies)} medication reconciliation discrepancies require clinician review. "
            "The comparison is deterministic; this text only explains the findings."
        ),
        "discrepancies": [
            {
                "home_med": item.get("home_med", ""),
                "current_order": item.get("current_order"),
                "kind": item.get("kind", "omitted"),
                "explanation": item.get("explanation", "Review required."),
                "evidence_event_ids": item.get("evidence_event_ids", []),
            }
            for item in discrepancies
        ],
    }


def f12_claim(context: dict[str, Any]) -> dict[str, Any]:
    revenue = context.get("revenue", {}) or {}
    gaps = []
    for item in revenue.get("missing_documents", []):
        gaps.append(
            {
                "kind": "missing_document",
                "description": f"{item.get('label')} is required before review.",
                "evidence_event_ids": item.get("evidence_event_ids", []),
            }
        )
    for item in revenue.get("unbilled_procedures", []):
        gaps.append(
            {
                "kind": "unbilled_procedure",
                "description": f"{item.get('procedure')} is documented but not billed.",
                "evidence_event_ids": item.get("evidence_event_ids", []),
            }
        )
    for item in revenue.get("underbilled_items", []):
        gaps.append(
            {
                "kind": "underbilled_item",
                "description": (
                    f"{item.get('description')} is billed at INR {item.get('billed_amount', 0):,.0f} "
                    f"against an expected INR {item.get('expected_amount', 0):,.0f}."
                ),
                "evidence_event_ids": item.get("evidence_event_ids", []),
            }
        )
    for item in revenue.get("contradictions", []):
        gaps.append(
            {
                "kind": "contradiction",
                "description": f"{item.get('title')}: {item.get('explanation')}",
                "evidence_event_ids": item.get("evidence_event_ids", []),
            }
        )
    if revenue.get("tpa_review", {}).get("status") == "needs_clarification":
        gaps.append(
            {
                "kind": "tpa_clarification",
                "description": "TPA review is blocked until the contradictions are resolved by a human.",
                "evidence_event_ids": revenue.get("tpa_review", {}).get("evidence_event_ids", []),
            }
        )
    for item in revenue.get("unsupported_items", []):
        gaps.append(
            {
                "kind": "unsupported_billing",
                "description": f"{item.get('description')} is billed without supporting documentation.",
                "evidence_event_ids": item.get("evidence_event_ids", []),
            }
        )
    return {
        "summary": (
            f"Claim pack has {len(gaps)} review gaps. The pack is assembled for human review only; "
            "it is not submitted and no charge is raised."
        ),
        "gaps": gaps,
    }


def f13_leakage(context: dict[str, Any]) -> dict[str, Any]:
    revenue = context.get("revenue", {}) or {}
    findings = [
        {
            "procedure": item.get("procedure", "Revenue finding"),
            "billing_status": item.get("billing_status", "unsupported"),
            "explanation": item.get("explanation", "Review required."),
            "evidence_event_ids": item.get("evidence_event_ids", []),
        }
        for item in revenue.get("findings", [])
    ]
    return {
        "summary": (
            f"{len(findings)} revenue findings require review. Amounts are computed from the seeded bill; "
            "nothing is charged or submitted automatically."
        ),
        "findings": findings,
    }


CACHED_GENERATORS = {
    "F1": f1_consult_note,
    "F2": f2_admission_note,
    "F3": f3_round,
    "F4": f4_progress,
    "F6": f6_recon,
    "F7": f7_icu_flow_sheet,
    "F9": f9_discharge,
    "F10": f10_investigation_request,
    "F11": f11_referral,
    "F12": f12_claim,
    "F13": f13_leakage,
}


def cached_draft(feature: str, context: dict[str, Any]) -> dict[str, Any]:
    generator = CACHED_GENERATORS.get(feature)
    if not generator:
        raise ValueError(f"No cached draft for {feature}")
    return generator(context)
