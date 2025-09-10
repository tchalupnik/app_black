"""GpioInputBinarySensorNew to receive signals."""

from __future__ import annotations

import logging
import time
import typing
from collections.abc import Callable
from datetime import timedelta

from boneio.const import PRESSED, RELEASED

from .base import BOTH, GpioBase, add_event_callback, add_event_detect

if typing.TYPE_CHECKING:
    from boneio.helper.events import EventBus

_LOGGER = logging.getLogger(__name__)


class GpioInputBinarySensorNew(GpioBase):
    """Represent Gpio sensor on input boards."""

    def __init__(
        self,
        pin: str,
        manager_press_callback: Callable,
        name: str,
        actions: dict,
        input_type: str,
        empty_message_after: bool,
        event_bus: EventBus,
        boneio_input: str = "",
        inverted: bool = False,
        initial_send: bool = False,
        bounce_time: timedelta | None = None,
        gpio_mode: str = "gpio",
    ) -> None:
        """Setup GPIO Input Button"""
        super().__init__(
            pin=pin,
            manager_press_callback=manager_press_callback,
            name=name,
            actions=actions,
            input_type=input_type,
            empty_message_after=empty_message_after,
            event_bus=event_bus,
            boneio_input=boneio_input,
            bounce_time=bounce_time,
            gpio_mode=gpio_mode,
        )
        self._state = self.is_pressed
        self.button_pressed_time = 0.0
        self._click_type = (RELEASED, PRESSED) if inverted else (PRESSED, RELEASED)
        self._pressed_state = (
            self._click_type[0] if self._state else self._click_type[1]
        )
        self._initial_send = initial_send
        _LOGGER.debug("Configured sensor pin %s", self._pin)
        add_event_detect(pin=self._pin, edge=BOTH)
        add_event_callback(pin=self._pin, callback=self.check_state)
        self._loop.call_soon_threadsafe(self.check_state, self._initial_send)

    def check_state(self, initial_send: bool = False) -> None:
        """Check if state has changed."""
        time_now = time.time()
        state = self.is_pressed
        if (time_now - self.button_pressed_time <= self._bounce_time) or (
            not initial_send and state == self._state
        ):
            return
        self._state = state
        self._pressed_state = self._click_type[0] if state else self._click_type[1]
        if self._pressed_state == PRESSED:
            self.button_pressed_time = time_now
        _LOGGER.debug(
            "Binary sensor: %s event on pin %s - %s at %s",
            self._pressed_state,
            self._pin,
            self.name,
            time_now,
        )
        self.press_callback(
            click_type=self._pressed_state, duration=None, start_time=time_now
        )
