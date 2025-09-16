"""GpioEventButton to receive signals."""

from __future__ import annotations

import asyncio
import logging
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

# TIMINGS FOR BUTTONS

DOUBLE_CLICK_DURATION_MS = 350
LONG_PRESS_DURATION_MS = 600

_LOGGER = logging.getLogger(__name__)


class GpioEventButton(GpioBase):
    """Represent Gpio input switch."""

    def __init__(
        self,
        config: EventConfig,
        manager_press_callback: Callable,
        event_bus: EventBus,
        gpio_manager: GpioManager,
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
        _LOGGER.debug("Configured stable listening for input pin %s", self.pin)
        self._timer_double = ClickTimer(
            delay=timedelta(milliseconds=DOUBLE_CLICK_DURATION_MS),
            action=lambda x: self.double_click_press_callback(),
        )
        self._timer_long = ClickTimer(
            delay=timedelta(milliseconds=LONG_PRESS_DURATION_MS),
            action=lambda x: self.press_callback(click_type=LONG, duration=x),
        )
        self._double_click_ran = False
        self._is_waiting_for_second_click = False
        self._long_press_ran = False
        asyncio.create_task(self._run())

    def double_click_press_callback(self):
        self._is_waiting_for_second_click = False
        if not self._state and not self._timer_long.is_waiting():
            self.press_callback(click_type=SINGLE, duration=None)
        else:
            _LOGGER.error(
                "Thats why it's not working %s %s",
                self._state,
                self._timer_long.is_waiting(),
            )

    async def _run(self) -> None:
        while True:
            self.check_state(state=self.is_pressed())
            await asyncio.sleep(self._bounce_time)

    def check_state(self, state: bool) -> None:
        if state == self._state:
            return
        self._state = state
        if state:  # is pressed?
            self._timer_long.start_timer()
            if self._timer_double.is_waiting():
                self._timer_double.reset()
                self._double_click_ran = True
                self.press_callback(click_type=DOUBLE, duration=None)
            else:
                self._timer_double.start_timer()
                self._is_waiting_for_second_click = True

        else:  # is released?
            if not self._is_waiting_for_second_click and not self._double_click_ran:
                if self._timer_long.is_waiting():
                    self.press_callback(click_type=SINGLE, duration=None)
            self._timer_long.reset()
            self._double_click_ran = False
