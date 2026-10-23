"""All routes. Every module in this package that defines ``router`` is included automatically,
so a feature can add a route file without editing this one."""

import importlib
import pkgutil

from fastapi import APIRouter, Depends

from ..services.identity import require_browsable_patient

router = APIRouter(prefix="/api")

# Hospital-level modules read the whole cohort (or no patient at all), so they skip the
# "only a browsable patient" check that every clinical module gets:
#   hospital:    /hospital/dashboard, /dashboard, /demo/status, /demo/reset
#   platform:    /users, /patients, /credits, /credits/packs
#   integration: /ingest/fhir, /integrations/status, /integrations/outbox/retry
HOSPITAL_LEVEL_MODULES = {"hospital", "platform", "integration"}

for _info in sorted(pkgutil.iter_modules(__path__), key=lambda info: info.name):
    if _info.name == "common":
        continue
    _module = importlib.import_module(f"{__name__}.{_info.name}")
    if hasattr(_module, "router"):
        if _info.name in HOSPITAL_LEVEL_MODULES:
            router.include_router(_module.router)
        else:
            router.include_router(_module.router, dependencies=[Depends(require_browsable_patient)])
