"""Tables added by feature work. Drop a module here; it is loaded automatically.

Decorate a table class with ``@resettable`` so demo reset clears it with the rest of the patient data.
New columns on existing tables go through ``app.db.register_columns``.
"""

from __future__ import annotations

import importlib
import pkgutil

RESETTABLE: list[type] = []


def resettable(cls):
    RESETTABLE.append(cls)
    return cls


for _info in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_info.name}")
