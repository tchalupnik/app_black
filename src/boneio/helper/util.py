from __future__ import annotations

import unicodedata
from typing import Any


def strip_accents(s: str) -> str:
    """Remove accents and spaces from a string."""
    return "".join(
        c
        for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn" and c != " "
    )


def find_key_by_value(d: dict, value: Any) -> Any:
    for k, v in d.items():
        if v == value:
            return k
    return None
