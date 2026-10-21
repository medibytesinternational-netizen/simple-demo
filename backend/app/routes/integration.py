"""Hospital-system link: receive FHIR from the HMS/EMR, report the link's state, retry sends."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..integrations import outbox
from ..integrations.ingest import ingest_bundle
from ..services.identity import require

router = APIRouter()


class FhirIngestRequest(BaseModel):
    system: str = Field(min_length=1, max_length=80)
    bundle: dict[str, Any]
    mrn: str | None = None  # only for a bundle that has no Patient resource


@router.post("/ingest/fhir", dependencies=[Depends(require("ingest"))])
def ingest_fhir(body: FhirIngestRequest, db: Session = Depends(get_db)):
    if body.bundle.get("resourceType") != "Bundle":
        raise HTTPException(400, "The body must contain a FHIR Bundle")
    result = ingest_bundle(db, body.system.strip(), body.bundle, body.mrn)
    db.commit()
    return result


@router.get("/integrations/status")
def integration_status(db: Session = Depends(get_db)):
    return outbox.status(db)


@router.post("/integrations/outbox/retry", dependencies=[Depends(require("ingest"))])
def retry_outbox(db: Session = Depends(get_db)):
    result = outbox.retry(db)
    db.commit()
    return result
