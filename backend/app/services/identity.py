"""Who is acting, which patient they are open on, and what that actor may do.

The demo has no passwords. The browser sends ``X-User-Id`` and ``X-Patient-Id``; a middleware
stores them in a per-request context so routes and services can read them without a request
object. There is one staff user, the attending physician (Dr. Meera Shah), and the patient is
Ravi. Task assignees ("Nurse Anita Rao") are data on a task, not accounts.

``ingest`` belongs to a system actor (the hospital system link). It is not selectable and is
not a person: it is chosen by the ``X-System-Id`` header on the ingest routes only.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class User:
    id: str
    name: str
    role: str
    home: str  # page this user lands on


USERS = [
    # The chief doctor ("doctor" role) walks the ward and hands out tasks.
    User("u_meera", "Dr. Meera Shah", "doctor", "/timeline"),
    # Staff who receive tasks. They see and work only the tasks given to their role.
    User("u_arjun", "Dr. Arjun Rao", "senior_doctor", "/tasks"),
    User("u_anita", "Nurse Anita Rao", "nurse", "/tasks"),
]
ROLE_LABELS = {"doctor": "Chief doctor", "senior_doctor": "Senior doctor", "nurse": "Nurse"}
TASK_ROLES = ("senior_doctor", "nurse")
DIRECTORY = {user.id: user for user in USERS}
DEFAULT_USER_ID = "u_meera"
DEFAULT_PATIENT_ID = "pat_ravi"

# Clinical screens show these patients only. The rest of the seeded cohort feeds the hospital
# dashboard and is never opened as a record.
BROWSABLE_PATIENT_IDS = frozenset({"pat_ravi"})

# System actors are not people and cannot be named in X-User-Id.
SYSTEM_ROLE = "integration"
SYSTEM_ACTOR_HEADER = "x-system-id"
SYSTEM_ACTORS = {
    "sys_hms": User("sys_hms", "Hospital system link", SYSTEM_ROLE, "/dashboard"),
}

# action -> roles allowed. Every action is the doctor's, except ingest, which is the system's.
PERMISSIONS: dict[str, set[str]] = {
    "consent": {"doctor"},
    "edit_draft": {"doctor"},
    "approve_draft": {"doctor"},
    "reject_draft": {"doctor"},
    "verify_allergy": {"doctor"},
    "accept_tasks": {"doctor"},
    "clinical_draft": {"doctor"},
    "discharge_draft": {"doctor"},
    "review_lab": {"doctor"},
    "run_rules": {"doctor"},
    "acknowledge_alert": {"doctor"},
    "dismiss_alert": {"doctor"},
    "reconcile": {"doctor"},
    "manage_task": {"doctor"},
    "work_task": {"doctor", "senior_doctor", "nurse"},
    "upload_document": {"doctor"},
    "confirm_document": {"doctor"},
    "send_request": {"doctor"},
    "records_request": {"doctor"},
    "revenue_work": {"doctor"},
    "order_medicine": {"doctor"},
    "give_medicine": {"doctor"},
    "resolve_discrepancy": {"doctor"},
    "record_reading": {"doctor"},
    "ingest": {SYSTEM_ROLE},
    "buy_credits": {"doctor"},
}

_user_id: ContextVar[str] = ContextVar("acting_user_id", default=DEFAULT_USER_ID)
_patient_id: ContextVar[str] = ContextVar("acting_patient_id", default=DEFAULT_PATIENT_ID)


def set_context(user_id: str | None, patient_id: str | None) -> tuple[Token, Token]:
    """Set the per-request actor and patient.

    Permissive about the patient on purpose: the cohort seed and the hospital dashboard pin
    cohort ids through here. Clinical routes refuse non-browsable patients through
    ``require_browsable_patient``.
    """
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


def is_browsable(patient_id: str | None) -> bool:
    return patient_id in BROWSABLE_PATIENT_IDS


def require_browsable_patient(request: Request) -> None:
    """Router dependency for clinical routes: 403 for a patient that is not browsable.

    Checks the patient named by ``X-Patient-Id`` and a ``{patient_id}`` path parameter.
    Hospital-level routes are left out of this dependency in ``routes/__init__.py``.
    """
    for patient_id in (current_patient_id(), request.path_params.get("patient_id")):
        if patient_id is not None and not is_browsable(patient_id):
            raise HTTPException(403, f"Patient {patient_id} is not available in this view")


def can(action: str, user: User | None = None) -> bool:
    return (user or acting_user()).role in PERMISSIONS[action]


def require(action: str):
    """Route dependency: 403 unless the actor may do ``action``.

    One decorator for every route, so a later role can be added without touching routes.
    Actions held by the system role are checked against ``X-System-Id`` instead of the user.
    """
    if action not in PERMISSIONS:
        raise KeyError(f"Unknown action {action}")
    system_only = PERMISSIONS[action] == {SYSTEM_ROLE}

    def check(request: Request) -> User:
        if system_only:
            actor = SYSTEM_ACTORS.get(request.headers.get(SYSTEM_ACTOR_HEADER) or "")
            if not actor:
                raise HTTPException(403, f"Only the hospital system link may {action.replace('_', ' ')}")
            return actor
        user = acting_user()
        if user.role not in PERMISSIONS[action]:
            raise HTTPException(403, f"{user.name} ({user.role}) may not {action.replace('_', ' ')}")
        return user

    return check
