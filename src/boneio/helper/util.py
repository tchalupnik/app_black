from __future__ import annotations

import unicodedata


def strip_accents(s: str) -> str:
    """Remove accents and spaces from a string."""
    return "".join(
        c
        for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn" and c != " "
    )
