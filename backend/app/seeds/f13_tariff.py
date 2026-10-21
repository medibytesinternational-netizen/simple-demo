"""Seed the F13 tariff. Upserts by code, so running it on every reset is safe."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models_ext.f13_tariff import TariffItem
from . import seed_hook

# (code, kind, description, unit_price). Codes match the seeded bill and procedure events.
DEFAULT_TARIFF: list[tuple[str, str, str, float]] = [
    ("97597", "procedure", "Wound debridement", 3500),
    ("PT01", "procedure", "Physiotherapy session", 2400),
    ("J01", "medication", "IV antibiotic administration", 4200),
    ("B05", "medication", "IV fluid infusion", 900),
    ("ROOM2", "bed_day", "Ward bed, per whole day", 3500),
    ("ICU01", "bed_day", "ICU bed, per whole day", 12000),
    ("LAB01", "investigation", "Laboratory test", 600),
    ("IMG01", "investigation", "Imaging study", 1800),
    ("US-RENAL", "investigation", "Renal ultrasound", 2200),
    ("CONS01", "consult", "Specialist consultation", 1200),
    ("CONS-NEPH", "consult", "Nephrology consultation", 1500),
]


def upsert_tariff(db: Session) -> None:
    for code, kind, description, price in DEFAULT_TARIFF:
        db.merge(TariffItem(code=code, kind=kind, description=description, unit_price=price))
    db.flush()


@seed_hook
def seed_f13_tariff(db: Session, mode: str) -> None:
    upsert_tariff(db)
