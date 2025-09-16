"""GpioInputBinarySensor to receive signals."""

from __future__ import annotations

import asyncio
import logging
import typing
from collections.abc import Callable

from boneio.config import BinarySensorConfig
from boneio.const import INPUT_SENSOR, PRESSED, RELEASED
from boneio.gpio_manager import GpioManager

from .base import GpioBase

if typing.TYPE_CHECKING:
    from boneio.helper.events import EventBus

_LOGGER = logging.getLogger(__name__)


class GpioInputBinarySensor(GpioBase):
    """Represent Gpio sensor on input boards."""

    def __init__(
        self,
        config: BinarySensorConfig,
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
            input_type=INPUT_SENSOR,
            empty_message_after=config.clear_message,
            event_bus=event_bus,
            boneio_input=config.boneio_input,
            bounce_time=config.bounce_time,
            gpio_mode=config.gpio_mode,
            gpio_manager=gpio_manager,
        )
        self._click_type = (
            (RELEASED, PRESSED) if config.inverted else (PRESSED, RELEASED)
        )
        _LOGGER.debug("Configured sensor pin %s", self.pin)
        asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            self.check_state(state=self.is_pressed())
            await asyncio.sleep(self._bounce_time)

    def check_state(self, state: bool) -> None:
        if state == self._state:
            return
        self._state = state
        click_type = self._click_type[0] if state else self._click_type[1]
        _LOGGER.debug("%s event on pin %s", click_type, self.pin)
        self.press_callback(click_type=click_type, duration=None)
