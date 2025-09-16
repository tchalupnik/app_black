"""GpioEventButtonNew to receive signals."""

from __future__ import annotations

import logging
import time
import typing
from collections.abc import Callable
from datetime import timedelta

from boneio.config import EventConfig
from boneio.const import DOUBLE, INPUT, LONG, SINGLE
from boneio.gpio_manager import GpioManager
from boneio.helper import ClickTimer

from .base import GpioBase

if typing.TYPE_CHECKING:
    from boneio.helper.events import EventBus

_LOGGER = logging.getLogger(__name__)

# TIMINGS FOR BUTTONS
DOUBLE_CLICK_DURATION_MS = 220
LONG_PRESS_DURATION_MS = 400


class GpioEventButtonNew(GpioBase):
    """Represent Gpio input switch."""

    def __init__(
        self,
        config: EventConfig,
        gpio_manager: GpioManager,
        manager_press_callback: Callable,
        event_bus: EventBus,
    ) -> None:
        """Setup GPIO Input Button"""
        super().__init__(
            pin=config.pin,
            manager_press_callback=manager_press_callback,
            name=config.identifier(),
            actions=config.actions,
            input_type=INPUT,
            empty_message_after=config.clear_message,
            event_bus=event_bus,
            boneio_input=config.boneio_input,
            gpio_mode=config.gpio_mode,
            gpio_manager=gpio_manager,
            bounce_time=config.bounce_time,
        )
        self.button_pressed_time = 0.0
        self.last_click_time = 0.0

        # Initialize timers
        self._timer_double = ClickTimer(
            delay=timedelta(milliseconds=DOUBLE_CLICK_DURATION_MS),
            action=lambda x: self.single_click_callback(),
        )
        self._timer_long = ClickTimer(
            delay=timedelta(milliseconds=LONG_PRESS_DURATION_MS),
            action=lambda x: self.long_click_callback(x),
        )

        # State tracking
        self._double_click_possible = (
            False  # True after first click until window expires
        )

        self.gpio_manager.init(pin=self.pin, mode="in", pull_mode="gpio_pu")
        self.gpio_manager.add_event_callback(pin=self.pin, callback=self.check_state)
        _LOGGER.debug("Configured NEW listening for input pin %s", self.pin)

    def single_click_callback(self):
        """Called when double click window expires without second click."""
        if not self._state:  # Only trigger if button is released
            self.press_callback(click_type=SINGLE, duration=None)
        self._double_click_possible = False

    def double_click_callback(self):
        """Handle double click."""
        self.press_callback(click_type=DOUBLE, duration=None)
        self._double_click_possible = False
        self._timer_double.reset()  # Cancel pending single click

    def long_click_callback(self, duration: float):
        """Handle long press."""
        self._double_click_possible = False  # Cancel any pending clicks
        self._timer_double.reset()
        self.press_callback(click_type=LONG, duration=duration)

    def check_state(self) -> None:
        time_now = time.time()
        self._state = self.is_pressed()

        if self._state:  # Button pressed
            # Ignore bounces
            if time_now - self.button_pressed_time < self._bounce_time:
                return

            self.button_pressed_time = time_now

            if self._double_click_possible:
                # Second press within window - trigger double click
                self.double_click_callback()
            else:
                # First press - start timers
                self._timer_long.start_timer()
                self._timer_double.start_timer()
                self._double_click_possible = True

        else:  # Button released
            self._timer_long.reset()  # Cancel long press detection
