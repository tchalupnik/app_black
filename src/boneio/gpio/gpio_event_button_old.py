"""GpioEventButton to receive signals."""

from __future__ import annotations

import logging
from dataclasses import field

import anyio

from boneio.const import DOUBLE, LONG, SINGLE
from boneio.helper import ClickTimer

from .base import GpioBase

# TIMINGS FOR BUTTONS

DOUBLE_CLICK_DURATION_S = 0.35
LONG_PRESS_DURATION_S = 0.6

_LOGGER = logging.getLogger(__name__)


class GpioEventButton(GpioBase):
    """Represent Gpio input switch."""

    input_type: str = "input"

    double_click_ran: bool = field(default=False, init=False)
    is_waiting_for_second_click: bool = field(default=False, init=False)
    long_press_ran: bool = field(default=False, init=False)

    def __init_post__(self) -> None:
        """Setup GPIO Input Button"""
        _LOGGER.debug("Configured stable listening for input pin %s", self.pin)
        self._timer_double = ClickTimer(
            tg=self.tg,
            delay=DOUBLE_CLICK_DURATION_S,
            action=lambda x: self.double_click_press_callback(),
        )
        self._timer_long = ClickTimer(
            tg=self.tg,
            delay=LONG_PRESS_DURATION_S,
            action=lambda x: self.press_callback(click_type=LONG, duration=x),
        )
        self.tg.start_soon(self._run)

    def double_click_press_callback(self) -> None:
        self._is_waiting_for_second_click = False
        if not self.state and not self._timer_long.is_waiting():
            self.press_callback(click_type=SINGLE)
        else:
            _LOGGER.error(
                "Thats why it's not working %s %s",
                self.state,
                self._timer_long.is_waiting(),
            )

    async def _run(self) -> None:
        while True:
            self.check_state(state=self.is_pressed())
            await anyio.sleep(self.bounce_time)

    def check_state(self, state: bool) -> None:
        if state == self.state:
            return
        self.state = state
        if state:  # is pressed?
            self.tg.start_soon(self._timer_long.start_timer)
            if self._timer_double.is_waiting():
                self._timer_double.reset()
                self._double_click_ran = True
                self.press_callback(click_type=DOUBLE)
            else:
                self.tg.start_soon(self._timer_double.start_timer)
                self._is_waiting_for_second_click = True

        else:  # is released?
            if not self._is_waiting_for_second_click and not self._double_click_ran:
                if self._timer_long.is_waiting():
                    self.press_callback(click_type=SINGLE)
            self._timer_long.reset()
            self._double_click_ran = False
