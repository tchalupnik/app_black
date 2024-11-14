"""Filter class to adjust sensor values."""

from __future__ import annotations
from typing import Optional
import logging

_LOGGER = logging.getLogger(__name__)


FILTERS = {
    "offset": lambda x, y: x + y,
    "round": lambda x, y: round(x, y),
    "multiply": lambda x, y: x * y if x else x,
    "filter_out": lambda x, y: None if x == y else x,
    "filter_out_greater": lambda x, y: None if x > y else x,
    "filter_out_lower": lambda x, y: None if x < y else x,
}


class Filter:
    _filters = []

    def _apply_filters(
        self, value: float | None, filters: Optional[list] = None
    ) -> float | None:
        filters = filters if filters is not None else self._filters
        for filter in filters:
            for k, v in filter.items():
                if k not in FILTERS:
                    _LOGGER.warning(
                        "Filter %s doesn't exists. Fix it in config.", k
                    )
                    continue
                if value is None:
                    return None
                value = FILTERS[k](value, v)
        return value
