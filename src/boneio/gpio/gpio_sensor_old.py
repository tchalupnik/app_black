"""GpioInputBinarySensor to receive signals."""

import asyncio
import logging
import typing
from collections.abc import Callable

from boneio.const import PRESSED, RELEASED

from .base import GpioBase

if typing.TYPE_CHECKING:
    from boneio.helper.events import EventBus
    from boneio.helper.timeperiod import TimePeriod

_LOGGER = logging.getLogger(__name__)


class GpioInputBinarySensor(GpioBase):
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
            bounce_time=bounce_time,
            gpio_mode=gpio_mode,
        )
        self._state = self.is_pressed
        self._click_type = (RELEASED, PRESSED) if inverted else (PRESSED, RELEASED)
        _LOGGER.debug("Configured sensor pin %s", self._pin)
        asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            self.check_state(state=self.is_pressed)
            await asyncio.sleep(self._bounce_time)

    def check_state(self, state: bool) -> None:
        if state == self._state:
            return
        self._state = state
        click_type = self._click_type[0] if state else self._click_type[1]
        _LOGGER.debug("%s event on pin %s", click_type, self._pin)
        self.press_callback(click_type=click_type, duration=None)
