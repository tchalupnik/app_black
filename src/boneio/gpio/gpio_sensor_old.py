"""GpioInputBinarySensor to receive signals."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

import anyio

from boneio.config import ActionConfig, BinarySensorActionTypes

from .base import GpioBase

_LOGGER = logging.getLogger(__name__)


@dataclass(kw_only=True)
class GpioInputBinarySensor(GpioBase):
    """Represent Gpio sensor on input boards."""

    # Redefinition to match types
    actions: dict[BinarySensorActionTypes, list[ActionConfig]]
    inverted: bool = False
    input_type: Literal["inputsensor"] = field(default="inputsensor", init=False)

    def __post_init__(
        self,
    ) -> None:
        super().__post_init__()
        """Setup GPIO Input Button"""
        self.click_type = (
            ("released", "pressed") if self.inverted else ("pressed", "released")
        )
        _LOGGER.debug("Configured sensor pin %s", self.pin)
        self.tg.start_soon(self._run)

    async def _run(self) -> None:
        while True:
            self.check_state(state=self.is_pressed())
            await anyio.sleep(self.bounce_time.total_seconds())

    def check_state(self, state: bool) -> None:
        if state == self.state:
            return
        self.state = state
        click_type = self.click_type[0] if state else self.click_type[1]
        _LOGGER.debug("%s event on pin %s", click_type, self.pin)
        self.press_callback(click_type=click_type)
