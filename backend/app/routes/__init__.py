from fastapi import APIRouter

from . import meta
from . import drafts
from . import notes
from . import icu_labs
from . import alerts
from . import medications
from . import tasks
from . import documents
from . import investigations
from . import referrals
from . import document_requests
from . import discharge
from . import revenue
from . import hospital

router = APIRouter(prefix="/api")
router.include_router(meta.router)
router.include_router(drafts.router)
router.include_router(notes.router)
router.include_router(icu_labs.router)
router.include_router(alerts.router)
router.include_router(medications.router)
router.include_router(tasks.router)
router.include_router(documents.router)
router.include_router(investigations.router)
router.include_router(referrals.router)
router.include_router(document_requests.router)
router.include_router(discharge.router)
router.include_router(revenue.router)
router.include_router(hospital.router)
