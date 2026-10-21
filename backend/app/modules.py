"""Canonical module registry for the MediBytes ARD demo.

This is deliberately explicit rather than inferred from route names. It is the
single place that maps the PRD's F1-F16 modules to the demo surfaces that
implement them, and it is checked by ``contract_check.py``.
"""

from __future__ import annotations

from typing import Any

MODULES: list[dict[str, Any]] = [
    {
        "id": "F1",
        "name": "Ambient OPD documentation",
        "workspace": "Notes → Consultation",
        "capability": "Consent-gated consultation capture and evidence-linked note draft",
        "llm": "gpt-4o + whisper-1",
        "human_gate": "Patient consent; clinician approval",
        "endpoints": [
            "/api/patients/{patient_id}/consents",
            "/api/notes/transcribe",
            "/api/notes/generate",
            "/api/drafts/{draft_id}/approve",
        ],
    },
    {
        "id": "F2",
        "name": "AI-assisted admission",
        "workspace": "Notes → Admission",
        "capability": "Admission file from existing records, with orders proposed and allergies flagged",
        "llm": "gpt-4o",
        "human_gate": "Allergy verification; clinician approval",
        "endpoints": [
            "/api/notes/generate",
            "/api/drafts/{draft_id}/verify-allergy",
            "/api/drafts/{draft_id}/approve",
        ],
    },
    {
        "id": "F3",
        "name": "Interdisciplinary handover",
        "workspace": "Notes → Round",
        "capability": "Round note, proposed nursing entries and proposed tasks",
        "llm": "gpt-4o",
        "human_gate": "Note approval; separate task acceptance",
        "endpoints": [
            "/api/notes/generate",
            "/api/drafts/{draft_id}/approve",
            "/api/drafts/{draft_id}/accept-tasks",
            "/api/tasks",
        ],
    },
    {
        "id": "F4",
        "name": "Daily progress notes",
        "workspace": "Notes → Progress",
        "capability": "Progress draft from documented change, with empty required sections left visible",
        "llm": "gpt-4o",
        "human_gate": "Clinician documents exam and plan before signing",
        "endpoints": [
            "/api/notes/generate",
            "/api/drafts/{draft_id}/approve",
        ],
    },
    {
        "id": "F5",
        "name": "Clinical Guardrail",
        "workspace": "Safety → Alerts",
        "capability": "Deterministic checks for drugs, labs, contradicting notes and unresolved actions",
        "llm": "gpt-4o phrasing only",
        "human_gate": "Dismissal requires a reason",
        "endpoints": [
            "/api/alerts",
            "/api/alerts/evaluate",
            "/api/alerts/{alert_id}/dismiss",
        ],
    },
    {
        "id": "F6",
        "name": "Medication reconciliation",
        "workspace": "Safety → Medication reconciliation",
        "capability": "Home list versus current plan on dose, route, frequency and indication",
        "llm": "gpt-4o explanation",
        "human_gate": "Clinician reviews each discrepancy",
        "endpoints": [
            "/api/medications/reconciliation",
            "/api/medications/reconciliation/generate",
        ],
    },
    {
        "id": "F7",
        "name": "ICU flow sheets",
        "workspace": "Notes → ICU chart",
        "capability": "Structured device readings assembled with units, timestamps and sources",
        "llm": "gpt-4o",
        "human_gate": "Clinician approval",
        "endpoints": [
            "/api/icu/flow-sheet",
            "/api/icu/flow-sheet/generate",
        ],
    },
    {
        "id": "F8",
        "name": "Medical OCR",
        "workspace": "Documents → Inbound",
        "capability": "Original report beside extraction; confidence per field; human confirmation",
        "llm": "gpt-4o vision / PDF text layer",
        "human_gate": "Low-confidence values need explicit confirmation before commit",
        "endpoints": [
            "/api/documents/upload",
            "/api/documents/{document_id}/confirm-field",
            "/api/documents/{document_id}/commit",
        ],
    },
    {
        "id": "F9",
        "name": "Discharge summary",
        "workspace": "Discharge",
        "capability": "Stay assembled from documented events, with deterministic medication list",
        "llm": "gpt-4o narrative",
        "human_gate": "Doctor signs and locks the encounter",
        "endpoints": [
            "/api/discharge/readiness",
            "/api/discharge/generate",
            "/api/drafts/{draft_id}/approve",
        ],
    },
    {
        "id": "F10",
        "name": "Investigation and radiology forms",
        "workspace": "Documents → Requisition",
        "capability": "Structured request with indication, diagnosis and allergies carried forward",
        "llm": "gpt-4o",
        "human_gate": "Clinician approval; demo export is a status change only",
        "endpoints": [
            "/api/investigation-requests",
            "/api/investigation-requests/generate",
            "/api/investigation-requests/{request_id}/export",
        ],
    },
    {
        "id": "F11",
        "name": "Smart referrals",
        "workspace": "Notes → Referral",
        "capability": "Specialist history and question, with consult status tracking",
        "llm": "gpt-4o",
        "human_gate": "Clinician approval; demo send is a status change only",
        "endpoints": [
            "/api/referrals",
            "/api/referrals/generate",
            "/api/referrals/{referral_id}/acknowledge",
            "/api/referrals/{referral_id}/complete",
        ],
    },
    {
        "id": "F12",
        "name": "Insurance and TPA documentation",
        "workspace": "Revenue → Claim pack",
        "capability": "Deterministic claim checklist, contradictions, TPA state and underbilling",
        "llm": "gpt-4o explanation only",
        "human_gate": "Review-only queue; no submission or charge",
        "endpoints": [
            "/api/revenue/claim-prep",
            "/api/revenue/claim-prep/prepare",
            "/api/revenue/claim-prep/explain",
            "/api/revenue/claim-prep/pack.html",
        ],
    },
    {
        "id": "F13",
        "name": "Revenue-leakage detection",
        "workspace": "Revenue → Leakage",
        "capability": "Comparison of documented procedures against seeded charges",
        "llm": "gpt-4o explanation only",
        "human_gate": "Review-only queue; no charge",
        "endpoints": [
            "/api/revenue/leakage",
            "/api/revenue/leakage/explain",
        ],
    },
    {
        "id": "F14",
        "name": "Hospital dashboard",
        "workspace": "Dashboard",
        "capability": "Hospital-scoped queues, ward load, claim posture and discrepancies",
        "llm": "none",
        "human_gate": "Management review; value KPIs labelled illustrative",
        "endpoints": [
            "/api/hospital/dashboard",
        ],
    },
    {
        "id": "F15",
        "name": "Task and escalation engine",
        "workspace": "Tasks",
        "capability": "Created, assigned, acknowledged, completed and escalated work",
        "llm": "none",
        "human_gate": "Assignee acknowledges; escalation needs a reason",
        "endpoints": [
            "/api/tasks",
            "/api/tasks/{task_id}/assign",
            "/api/tasks/{task_id}/acknowledge",
            "/api/tasks/{task_id}/escalate",
            "/api/tasks/escalations/run",
        ],
    },
    {
        "id": "F16",
        "name": "Unified patient timeline",
        "workspace": "Timeline",
        "capability": "Append-only events with author, time, provenance and current-state projection",
        "llm": "none",
        "human_gate": "Append-only; superseded events stay visible",
        "endpoints": [
            "/api/patients/{patient_id}/timeline",
            "/api/patients/{patient_id}/state",
            "/api/events/{event_id}",
        ],
    },
]


def module_registry() -> dict[str, Any]:
    return {
        "count": len(MODULES),
        "modules": MODULES,
        "support_views": [
            "Notes → Labs (support)",
            "Documents → Follow-up (support)",
        ],
    }
