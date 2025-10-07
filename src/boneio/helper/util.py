from __future__ import annotations

import sys
import unicodedata


def strip_accents(s: str) -> str:
    """Remove accents and spaces from a string."""
    return "".join(
        c
        for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn" and c != " "
    )


if sys.version_info >= (3, 12):
    from itertools import batched
else:
    from collections.abc import Iterable, Iterator
    from itertools import islice
    from typing import TypeVar

    T = TypeVar("T")

    def batched(iterable: Iterable[T], n: int) -> Iterator[tuple[T, ...]]:
        if n < 1:
            raise ValueError("n must be at least one")
        it = iter(iterable)
        while batch := tuple(islice(it, n)):
            yield batch
