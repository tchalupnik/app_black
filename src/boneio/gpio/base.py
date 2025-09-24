from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Final, Literal, TypeAlias

from boneio.config import ActionConfig, BinarySensorActionTypes, EventActionTypes
from boneio.const import (
    CONFIG_PIN,
    PRESSED,
    RELEASED,
)
from boneio.const import GPIO as GPIO_STR
from boneio.events import EventBus, InputEvent
from boneio.gpio_manager import GpioManager
from boneio.models import InputState

_LOGGER: Final = logging.getLogger(__name__)

ClickTypes: TypeAlias = Literal["single", "double", "long", "pressed", "released"]


def configure_pin(pin: str, mode: str = GPIO_STR) -> None:
    pin = f"{pin[0:3]}0{pin[3]}" if len(pin) == 4 else pin
    _LOGGER.debug("Configuring pin %s for mode %s.", pin, mode)
    subprocess.run(
        [CONFIG_PIN, pin, mode],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        timeout=1,
    )


class GpioBase:
    """Base class for initialize GPIO"""

    def __init__(
        self,
        gpio_manager: GpioManager,
        pin: str,
        manager_press_callback: Callable[
            [ClickTypes, GpioBase, str, bool, float | None],
            Awaitable[None],
        ],
        name: str,
        actions: dict[EventActionTypes | BinarySensorActionTypes, list[ActionConfig]],
        input_type,
        empty_message_after: bool,
        event_bus: EventBus,
        gpio_mode: str = "gpio",
        bounce_time: timedelta = timedelta(milliseconds=50),
        boneio_input: str = "",
    ) -> None:
        """Setup GPIO Input Button"""
        self.pin = pin
        self.gpio_manager = gpio_manager
        self.gpio_manager.init(pin=self.pin, mode="in", pull_mode=gpio_mode)
        self._bounce_time = bounce_time.total_seconds()
        self._loop = asyncio.get_running_loop()
        self._manager_press_callback = manager_press_callback
        self.name = name
        self.actions = actions
        self.input_type = input_type
        self._empty_message_after = empty_message_after
        self.boneio_input = boneio_input
        self._click_type = (PRESSED, RELEASED)
        self._state = self.is_pressed()
        self.last_state = "Unknown"
        self.last_press_timestamp = 0.0
        self._event_bus = event_bus
        self._event_lock = asyncio.Lock()

    def press_callback(
        self,
        click_type: ClickTypes,
        duration: float | None = None,
        start_time: float | None = None,
    ) -> None:
        """Handle press callback."""
        asyncio.run_coroutine_threadsafe(
            self._handle_press_with_lock(click_type, duration, start_time), self._loop
        )

    async def _handle_press_with_lock(
        self,
        click_type: ClickTypes,
        duration: float | None = None,
        start_time: float | None = None,
    ):
        """Handle press event with a lock to ensure sequential execution."""
        dur = None
        if start_time is not None:
            dur = time.time() - start_time
        _LOGGER.debug(
            "[%s] Attempting to acquire lock for event '%s'. Duration: %s",
            self.name,
            click_type,
            dur,
        )
        async with self._event_lock:
            _LOGGER.debug(
                "[%s] Acquired lock for event '%s'. Processing...",
                self.name,
                click_type,
            )
            self.last_press_timestamp = time.time()
            _LOGGER.debug(
                "Press callback: %s on pin %s - %s. Duration: %s",
                click_type,
                self.pin,
                self.name,
                self.last_press_timestamp - start_time,
            )
            self.last_state = click_type
            await self._manager_press_callback(
                click_type,
                self,
                self._empty_message_after,
                duration,
                start_time,
            )
            self._event_bus.trigger_event(
                InputEvent(
                    entity_id=self.pin,
                    event_state=InputState(
                        name=self.name,
                        state=self.last_state,
                        type=self.input_type,
                        timestamp=self.last_press_timestamp,
                        boneio_input=self.boneio_input,
                    ),
                )
            )
        _LOGGER.debug("[%s] Released lock for event '%s'", self.name, click_type)

    def is_pressed(self) -> bool:
        """Is button pressed."""
        return self.gpio_manager.read(self.pin)

    @property
    def pressed_state(self) -> str:
        """Pressed state for"""
        return self._click_type[0] if self._state else self._click_type[1]
