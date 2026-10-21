"""All routes. Every module in this package that defines ``router`` is included automatically,
so a feature can add a route file without editing this one."""

import importlib
import pkgutil

from fastapi import APIRouter

router = APIRouter(prefix="/api")

for _info in sorted(pkgutil.iter_modules(__path__), key=lambda info: info.name):
    if _info.name == "common":
        continue
    _module = importlib.import_module(f"{__name__}.{_info.name}")
    if hasattr(_module, "router"):
        router.include_router(_module.router)
