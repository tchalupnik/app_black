"""GpioInputBinarySensorNew to receive signals."""

from __future__ import annotations

import logging
import time
import typing
from collections.abc import Callable

from boneio.config import BinarySensorActionTypes, BinarySensorConfig, EventActionTypes
from boneio.const import INPUT_SENSOR, PRESSED, RELEASED
from boneio.gpio_manager import GpioManager

from .base import GpioBase

if typing.TYPE_CHECKING:
    from boneio.helper.events import EventBus

_LOGGER = logging.getLogger(__name__)


class GpioInputBinarySensorNew(GpioBase):
    """Represent Gpio sensor on input boards."""

    def __init__(
        self,
        config: BinarySensorConfig,
        manager_press_callback: Callable,
        actions: dict[
            EventActionTypes | BinarySensorActionTypes, list[dict[str, typing.Any]]
        ],
        event_bus: EventBus,
        gpio_manager: GpioManager,
    ) -> None:
        """Setup GPIO Input Button"""
        super().__init__(
            pin=config.pin,
            manager_press_callback=manager_press_callback,
            name=config.identifier(),
            actions=actions,
            input_type=INPUT_SENSOR,
            empty_message_after=config.clear_message,
            event_bus=event_bus,
            boneio_input=config.boneio_input,
            bounce_time=config.bounce_time,
            gpio_mode=config.gpio_mode,
            gpio_manager=gpio_manager,
        )
        self._state = self.is_pressed
        self.button_pressed_time = 0.0
        self._click_type = (
            (RELEASED, PRESSED) if config.inverted else (PRESSED, RELEASED)
        )
        self._pressed_state = (
            self._click_type[0] if self._state else self._click_type[1]
        )
        self._initial_send = config.initial_send
        _LOGGER.debug("Configured sensor pin %s", self.pin)
        self.gpio_manager.add_event_callback(
            pin=self.pin,
            callback=self.check_state,
            debounce_period=config.bounce_time,
        )
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
            self.pin,
            self.name,
            time_now,
        )
        self.press_callback(
            click_type=self._pressed_state, duration=None, start_time=time_now
        )
