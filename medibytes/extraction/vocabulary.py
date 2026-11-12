"""The curated mini drug list: canonical names plus observed mishearings (aliases).

This is the project's own formulary and the vocabulary the gold data is written
in, so it always wins over the national reference when both know a name.
"""
import json
from functools import lru_cache

from ..config import ASSETS_DIR

_MINI_LIST = ASSETS_DIR / "drug_list_mini.json"


@lru_cache(maxsize=1)
def _drug_list() -> tuple:
    with open(_MINI_LIST, encoding="utf-8") as f:
        return tuple(json.load(f))


def load_drug_list():
    """[{name, aliases}] - parsed once; raises if the asset is missing."""
    return list(_drug_list())
