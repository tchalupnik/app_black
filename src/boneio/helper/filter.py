"""Filter class to adjust sensor values."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from boneio.config import Filters

_LOGGER = logging.getLogger(__name__)


FILTERS: dict[Filters, Callable[[float, float], float | None]] = {
    "offset": lambda x, y: x + y,
    "round": lambda x, y: round(x, int(y)),
    "multiply": lambda x, y: x * y if x else x,
    "filter_out": lambda x, y: None if x == y else x,
    "filter_out_greater": lambda x, y: None if x > y else x,
    "filter_out_lower": lambda x, y: None if x < y else x,
    "encode_temperature": lambda x, y: (int(x * int(y)) << 1) | 1,
}


@dataclass
class Filter:
    filter: list[dict[Filters, float]] = field(default_factory=list)

    def apply_filters(
        self, value: float | None, filters: list[dict[Filters, float]] | None = None
    ) -> float | None:
        filters = filters if filters is not None else self.filter
        for filter in filters:
            for k, v in filter.items():
                if k not in FILTERS:
                    _LOGGER.warning("Filter %s doesn't exists. Fix it in config.", k)
                    continue
                value = FILTERS[k](value, v)
        return value
