"""GpioInputBinarySensorNew to receive signals."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Literal

from .base import GpioBase

_LOGGER = logging.getLogger(__name__)


@dataclass(kw_only=True)
class GpioInputBinarySensorNew(GpioBase):
    """Represent Gpio sensor on input boards."""

    inverted: bool = False
    initial_send: bool = False
    input_type: Literal["inpusensor"] = "inpusensor"

    button_pressed_time: float = field(default=0.0, init=False)

    def __post_init__(
        self,
    ) -> None:
        """Setup GPIO Input Button"""
        self.click_type = (
            ("released", "pressed") if self.inverted else ("pressed", "released")
        )
        self._pressed_state = self.click_type[0] if self.state else self.click_type[1]
        _LOGGER.debug("Configured sensor pin %s", self.pin)
        self.gpio_manager.add_event_callback(
            pin=self.pin,
            callback=self.check_state,
            debounce_period=self.bounce_time,
        )
        self.check_state()

    def check_state(self) -> None:
        """Check if state has changed."""
        time_now = time.time()
        state = self.is_pressed()
        if (
            time_now - self.button_pressed_time <= self.bounce_time.total_seconds()
        ) or (not self.initial_send and state == self.state):
            return
        self.state = state
        self._pressed_state = self.click_type[0] if state else self.click_type[1]
        if self._pressed_state == "pressed":
            self.button_pressed_time = time_now
        _LOGGER.debug(
            "Binary sensor: %s event on pin %s - %s at %s",
            self._pressed_state,
            self.pin,
            self.name,
            time_now,
        )
        self.press_callback(click_type=self._pressed_state, start_time=time_now)
