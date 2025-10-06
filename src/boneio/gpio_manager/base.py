from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import timedelta
from enum import Enum
from typing import Literal


class Edge(Enum):
    BOTH = "BOTH"
    FALLING = "FALLING"
    RISING = "RISING"


class GpioManagerBase(ABC):
    @abstractmethod
    def init(
        self,
        pin: str,
        mode: Literal["in", "out"],
        pull_mode: Literal["gpio", "gpio_pu", "gpio_pd", "gpio_input"] = "gpio",
    ) -> None:
        """Set up a GPIO as input."""

    @abstractmethod
    def write(self, pin: str, value: Literal["high", "low"]) -> None:
        """Write a value to a GPIO."""

    @abstractmethod
    def read(self, pin: str) -> bool:
        """Read a value from a GPIO."""

    @abstractmethod
    def add_event_callback(
        self,
        pin: str,
        callback: Callable[[], None],
        edge: Edge = Edge.BOTH,
        debounce_period: timedelta = timedelta(milliseconds=100),
    ) -> None:
        pass
