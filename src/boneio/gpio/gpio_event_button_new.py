"""GpioEventButtonNew to receive signals."""

from __future__ import annotations

import logging
import time
import typing
from collections.abc import Callable

from boneio.const import DOUBLE, LONG, SINGLE
from boneio.helper import ClickTimer
from boneio.helper.timeperiod import TimePeriod

from .base import BOTH, GpioBase, edge_detect

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
        pin: str,
        manager_press_callback: Callable,
        name: str,
        actions: dict,
        input_type: str,
        empty_message_after: bool,
        event_bus: EventBus,
        boneio_input: str = "",
        bounce_time: TimePeriod | None = None,
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
            bounce_time=bounce_time or TimePeriod(milliseconds=50),
            gpio_mode=gpio_mode,
        )
        self._state = self.is_pressed
        self.button_pressed_time = 0.0
        self.last_click_time = 0.0

        # Initialize timers
        self._timer_double = ClickTimer(
            delay=TimePeriod(milliseconds=DOUBLE_CLICK_DURATION_MS),
            action=lambda x: self.single_click_callback(),
        )
        self._timer_long = ClickTimer(
            delay=TimePeriod(milliseconds=LONG_PRESS_DURATION_MS),
            action=lambda x: self.long_click_callback(x),
        )

        # State tracking
        self._double_click_possible = (
            False  # True after first click until window expires
        )

        edge_detect(pin=self._pin, callback=self.check_state, bounce=0, edge=BOTH)
        _LOGGER.debug("Configured NEW listening for input pin %s", self._pin)

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

    def check_state(self, _) -> None:
        time_now = time.time()
        self._state = self.is_pressed

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
