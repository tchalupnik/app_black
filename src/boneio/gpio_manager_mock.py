from __future__ import annotations

import logging
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import timedelta
from enum import Enum
from typing import Literal

_LOGGER = logging.getLogger(__name__)


class Edge(Enum):
    BOTH = "BOTH"
    FALLING = "FALLING"
    RISING = "RISING"


class GpioManagerMock:
    @classmethod
    @contextmanager
    def create(cls) -> Generator[GpioManagerMock]:
        yield cls()

    def init(
        self,
        pin: str,
        mode: Literal["in", "out"],
        pull_mode: Literal["gpio", "gpio_pu", "gpio_pd", "gpio_input"] = "gpio",
    ) -> None:
        """Set up a GPIO as input."""

    def write(self, pin: str, value: Literal["high", "low"]) -> None:
        """Write a value to a GPIO."""
        _LOGGER.debug("[%s] write to pin, value %s", pin, value)

    def read(self, pin: str) -> bool:
        """Read a value from a GPIO."""
        _LOGGER.debug("[%s] read from pin", pin)
        return True

    def add_event_callback(
        self,
        pin: str,
        callback: Callable[[], None],
        edge: Edge = Edge.BOTH,
        debounce_period: timedelta = timedelta(milliseconds=100),
    ) -> None:
        pass
