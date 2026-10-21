"""AI credits consumed per operation (PRD, commercial model).

The PRD's illustrative schedule: reading a report 1, voice note 2, medicine reconciliation 2,
report analysis 4, discharge summary 5, sold in monthly packs of 5,000, 15,000 or 50,000.
Decisions the PRD leaves open, made here so they can be changed in one place:
- one credit covers a whole document, not a page;
- "report analysis" is the reading of a report that is not a lab report (radiology, discharge letter).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import CreditAccount, CreditEntry
from .identity import acting_name, current_patient_id
from .timeline import new_id

SCHEDULE = {
    "report_reading": 1,
    "voice_note": 2,
    "medicine_reconciliation": 2,
    "report_analysis": 4,
    "discharge_summary": 5,
}
PACKS = [5000, 15000, 50000]
DEFAULT_PACK = PACKS[0]
ACCOUNT_ID = "default"


class CreditsExhausted(ValueError):
    """Raised when the pack cannot cover an operation; mapped to HTTP 402."""


def _account(db: Session) -> CreditAccount:
    account = db.get(CreditAccount, ACCOUNT_ID)
    if not account:
        account = CreditAccount(id=ACCOUNT_ID, pack_size=DEFAULT_PACK, balance=DEFAULT_PACK, updated_at=utcnow())
        db.add(account)
        db.flush()
    return account


def charge(
    db: Session,
    operation: str,
    *,
    feature: str | None = None,
    mode: str | None = None,
    llm_call_id: str | None = None,
) -> CreditEntry:
    """Spend the credits for one operation. Call it before the operation does its work."""
    units = SCHEDULE[operation]
    account = _account(db)
    if account.balance < units:
        raise CreditsExhausted(
            f"{operation.replace('_', ' ').capitalize()} needs {units} credits; {account.balance} left. Add a pack to continue."
        )
    account.balance -= units
    account.updated_at = utcnow()
    entry = CreditEntry(
        id=new_id("crd"),
        operation=operation,
        units=units,
        balance_after=account.balance,
        feature=feature,
        mode=mode,
        llm_call_id=llm_call_id,
        patient_id=current_patient_id(),
        actor=acting_name(),
        created_at=utcnow(),
    )
    db.add(entry)
    db.flush()
    return entry


def status(db: Session, recent: int = 20) -> dict:
    account = _account(db)
    rows = db.scalars(select(CreditEntry).order_by(CreditEntry.created_at.desc()).limit(recent)).all()
    return {
        "pack_size": account.pack_size,
        "balance": account.balance,
        "used": account.pack_size - account.balance,
        "packs": PACKS,
        "schedule": SCHEDULE,
        "ledger": [
            {
                "id": row.id,
                "operation": row.operation,
                "units": row.units,
                "balance_after": row.balance_after,
                "feature": row.feature,
                "mode": row.mode,
                "llm_call_id": row.llm_call_id,
                "actor": row.actor,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


def add_pack(db: Session, size: int) -> dict:
    if size not in PACKS:
        raise ValueError(f"Packs are {', '.join(str(p) for p in PACKS)} credits")
    account = _account(db)
    account.pack_size += size
    account.balance += size
    account.updated_at = utcnow()
    db.flush()
    return status(db)


def reset(db: Session) -> None:
    db.query(CreditEntry).delete()
    account = _account(db)
    account.pack_size = DEFAULT_PACK
    account.balance = DEFAULT_PACK
    account.updated_at = utcnow()
    db.flush()
