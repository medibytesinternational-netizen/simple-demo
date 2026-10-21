"""Who is acting, which patient they are looking at, and what each role may do.

The demo has no passwords. The browser sends ``X-User-Id`` and ``X-Patient-Id``; a middleware
stores them in a per-request context so routes and services can read them without a request
object. With no header the acting user is the attending physician and the patient is Ravi, so
scripts written before roles existed keep working.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True)
class User:
    id: str
    name: str
    role: str
    home: str  # page this role lands on


USERS = [
    User("u_meera", "Dr. Meera Shah", "doctor", "/timeline"),
    User("u_anita", "Nurse Anita Rao", "nurse", "/tasks"),
    User("u_dev", "Pharmacist Dev Patel", "pharmacist", "/safety"),
    User("u_billing", "Billing desk", "billing", "/revenue"),
    User("u_mgmt", "Hospital management", "management", "/dashboard"),
    User("u_hms", "Hospital system link", "integration", "/dashboard"),
]
DIRECTORY = {user.id: user for user in USERS}
DEFAULT_USER_ID = "u_meera"
DEFAULT_PATIENT_ID = "pat_ravi"

# action -> roles allowed. Management has no write actions, so it is read-only.
PERMISSIONS: dict[str, set[str]] = {
    "consent": {"doctor", "nurse"},
    "edit_draft": {"doctor", "billing"},
    "approve_draft": {"doctor", "billing"},
    "reject_draft": {"doctor", "billing"},
    "verify_allergy": {"doctor"},
    "accept_tasks": {"doctor", "nurse"},
    "clinical_draft": {"doctor", "nurse", "pharmacist"},
    "discharge_draft": {"doctor"},
    "review_lab": {"doctor"},
    "run_rules": {"doctor", "nurse", "pharmacist", "integration"},
    "acknowledge_alert": {"doctor", "nurse", "pharmacist"},
    "dismiss_alert": {"doctor"},
    "reconcile": {"doctor", "pharmacist"},
    "manage_task": {"doctor", "nurse", "pharmacist", "billing"},
    "work_task": {"doctor", "nurse", "pharmacist", "billing"},
    "upload_document": {"doctor", "nurse", "billing"},
    "confirm_document": {"doctor", "nurse"},
    "send_request": {"doctor", "nurse"},
    "records_request": {"doctor", "billing"},
    "revenue_work": {"doctor", "billing"},
    # added by feature work
    "order_medicine": {"doctor"},
    "give_medicine": {"nurse"},
    "resolve_discrepancy": {"doctor", "pharmacist"},
    "record_reading": {"doctor", "nurse", "integration"},
    "ingest": {"integration"},
    "buy_credits": {"billing"},
}

# Revenue drafts are the only drafts billing may edit, approve or reject.
BILLING_FEATURES = {"F12", "F13"}

_user_id: ContextVar[str] = ContextVar("acting_user_id", default=DEFAULT_USER_ID)
_patient_id: ContextVar[str] = ContextVar("acting_patient_id", default=DEFAULT_PATIENT_ID)


def set_context(user_id: str | None, patient_id: str | None) -> tuple[Token, Token]:
    if user_id and user_id not in DIRECTORY:
        raise ValueError(f"Unknown user {user_id}")
    return _user_id.set(user_id or DEFAULT_USER_ID), _patient_id.set(patient_id or DEFAULT_PATIENT_ID)


def reset_context(tokens: tuple[Token, Token]) -> None:
    _user_id.reset(tokens[0])
    _patient_id.reset(tokens[1])


def acting_user() -> User:
    return DIRECTORY[_user_id.get()]


def acting_name() -> str:
    return acting_user().name


def current_patient_id() -> str:
    return _patient_id.get()


def can(action: str, user: User | None = None) -> bool:
    return (user or acting_user()).role in PERMISSIONS[action]


def require(action: str):
    """Route dependency: 403 unless the acting user's role may do ``action``."""
    if action not in PERMISSIONS:
        raise KeyError(f"Unknown action {action}")

    def check() -> User:
        user = acting_user()
        if user.role not in PERMISSIONS[action]:
            raise HTTPException(403, f"{user.name} ({user.role}) may not {action.replace('_', ' ')}")
        return user

    return check


def require_feature_role(action: str, feature: str) -> None:
    """Billing may act on revenue drafts only."""
    user = acting_user()
    if user.role == "billing" and feature not in BILLING_FEATURES:
        raise HTTPException(403, f"{user.name} may only {action.replace('_', ' ')} claim and revenue drafts")
