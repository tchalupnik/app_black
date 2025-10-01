"""GpioEventButtonNew to receive signals."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from boneio.helper import ClickTimer

from .base import GpioBase

_LOGGER = logging.getLogger(__name__)

# TIMINGS FOR BUTTONS
DOUBLE_CLICK_DURATION_S = 0.22
LONG_PRESS_DURATION_S = 0.4


@dataclass(kw_only=True)
class GpioEventButtonNew(GpioBase):
    """Represent Gpio input switch."""

    input_type: str = field(default="input", init=False)
    button_pressed_time: float = field(default=0.0, init=False)
    last_click_time: float = field(default=0.0, init=False)

    # State tracking
    # True after first click until window expires
    double_click_possible: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        """Setup GPIO Input Button"""
        super().__post_init__()

        # Initialize timers
        self._timer_double = ClickTimer(
            tg=self.tg,
            delay=DOUBLE_CLICK_DURATION_S,
            action=lambda x: self.single_click_callback(),
        )
        self._timer_long = ClickTimer(
            tg=self.tg,
            delay=LONG_PRESS_DURATION_S,
            action=lambda x: self.long_click_callback(x),
        )

        self.gpio_manager.add_event_callback(pin=self.pin, callback=self.check_state)
        _LOGGER.debug("Configured NEW listening for input pin %s", self.pin)

    def single_click_callback(self) -> None:
        """Called when double click window expires without second click."""
        if not self.state:  # Only trigger if button is released
            self.press_callback(
                click_type="single", start_time=self.button_pressed_time
            )
        self.double_click_possible = False

    def double_click_callback(self) -> None:
        """Handle double click."""
        self.press_callback(click_type="double", start_time=self.button_pressed_time)
        self.double_click_possible = False
        self._timer_double.reset()  # Cancel pending single click

    def long_click_callback(self, duration: float) -> None:
        """Handle long press."""
        self.double_click_possible = False  # Cancel any pending clicks
        self._timer_double.reset()
        self.press_callback(
            click_type="long", duration=duration, start_time=self.button_pressed_time
        )

    def check_state(self) -> None:
        """Check state - called from GPIO interrupt."""
        time_now = time.time()
        self.state = self.is_pressed()
        _LOGGER.debug(
            "[PIN: %s] State %s, time now: %s, button pressed time: %s, double click possible %s",
            self.pin,
            self.state,
            time_now,
            self.button_pressed_time,
            self.double_click_possible,
        )

        if self.state:  # Button pressed
            # Ignore bounces
            if time_now - self.button_pressed_time < self.bounce_time.total_seconds():
                return

            self.button_pressed_time = time_now

            if self.double_click_possible:
                # Second press within window - trigger double click
                self.double_click_callback()
            else:
                # First press - start timers
                self.tg.start_soon(self._timer_long.start_timer)
                self.tg.start_soon(self._timer_double.start_timer)
                self.double_click_possible = True

        else:  # Button released
            self._timer_long.reset()  # Cancel long press detection
