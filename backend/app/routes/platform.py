"""Shared platform routes: who can act, which patients exist, and AI credits."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Encounter, Patient
from ..services import credits
from ..services.identity import DIRECTORY, PERMISSIONS, USERS, acting_user, require

router = APIRouter()


class PackRequest(BaseModel):
    size: int


def user_dict(user) -> dict:
    return {"id": user.id, "name": user.name, "role": user.role, "home": user.home}


def allowed_actions(user=None) -> list[str]:
    role = (user or acting_user()).role
    return sorted(action for action, roles in PERMISSIONS.items() if role in roles)


@router.get("/users")
def users():
    return {"users": [user_dict(user) for user in USERS], "acting": user_dict(acting_user())}


@router.get("/patients")
def patients(db: Session = Depends(get_db)):
    rows = db.scalars(select(Patient).order_by(Patient.name)).all()
    encounters = db.scalars(select(Encounter).order_by(Encounter.admitted_at.desc())).all()
    latest: dict[str, Encounter] = {}
    for encounter in encounters:
        latest.setdefault(encounter.patient_id, encounter)
    return {
        "patients": [
            {
                "id": patient.id,
                "mrn": patient.mrn,
                "name": patient.name,
                "age": patient.age,
                "sex": patient.sex,
                "ward": latest[patient.id].ward if patient.id in latest else None,
                "bed": latest[patient.id].bed if patient.id in latest else None,
                "encounter_status": latest[patient.id].status if patient.id in latest else None,
            }
            for patient in rows
        ]
    }


@router.get("/credits")
def credit_status(db: Session = Depends(get_db)):
    return credits.status(db)


@router.post("/credits/packs", dependencies=[Depends(require("buy_credits"))])
def credit_pack(body: PackRequest, db: Session = Depends(get_db)):
    result = credits.add_pack(db, body.size)
    db.commit()
    return result


__all__ = ["router", "allowed_actions", "user_dict", "DIRECTORY"]
