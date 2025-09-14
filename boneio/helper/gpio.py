from __future__ import annotations

import asyncio
import logging
import time
import subprocess
from typing import Awaitable, Callable

from boneio.const import (
    CONFIG_PIN,
    GPIO_MODE,
    PRESSED,
    RELEASED,
    ClickTypes,
)
from boneio.const import GPIO as GPIO_STR
from boneio.helper.events import EventBus
from boneio.helper.gpiod import GpioManager
from boneio.helper.timeperiod import TimePeriod
from boneio.models import InputState

_LOGGER = logging.getLogger(__name__)


def configure_pin(pin: str, mode: str = GPIO_STR) -> None:
    pin = f"{pin[0:3]}0{pin[3]}" if len(pin) == 4 else pin
    _LOGGER.debug(f"Configuring pin {pin} for mode {mode}.")
    subprocess.run(
        [CONFIG_PIN, pin, mode],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        timeout=1,
    )

class GpioBaseClass:
    """Base class for initialize GPIO"""

    def __init__(
        self,
        gpio_manager: GpioManager,
        pin: str,
        manager_press_callback: Callable[
            [ClickTypes, GpioBaseClass, str, bool, float | None],
            Awaitable[None],
        ],
        name: str,
        actions: dict,
        input_type,
        empty_message_after: bool,
        event_bus: EventBus,
        boneio_input: str = "",
        **kwargs,
    ) -> None:
        """Setup GPIO Input Button"""
        self.gpio_manager = gpio_manager
        self._pin = pin
        gpio_mode = kwargs.get(GPIO_MODE, GPIO_STR)
        bounce_time: TimePeriod = kwargs.get(
            "bounce_time", TimePeriod(milliseconds=50)
        )
        self._bounce_time = bounce_time.total_in_seconds
        self._loop = asyncio.get_running_loop()
        self._manager_press_callback = manager_press_callback
        self._name = name
        self.gpio_manager.setup_input(pin=self._pin, pull_mode=gpio_mode)
        self._actions = actions
        self._input_type = input_type
        self._empty_message_after = empty_message_after
        self._boneio_input = boneio_input
        self._click_type = (PRESSED, RELEASED)
        self._state = self.is_pressed
        self._last_state = "Unknown"
        self._last_timestamp = 0.0
        self._event_bus = event_bus
        self._event_lock = asyncio.Lock()

    @property
    def boneio_input(self) -> str:
        return self._boneio_input or ""

    def press_callback(
        self, click_type: ClickTypes, duration: float | None = None, start_time: float | None = None
    ) -> None:
        """Handle press callback."""
        asyncio.run_coroutine_threadsafe(self._handle_press_with_lock(click_type, duration, start_time), self._loop)
        
        
    async def _handle_press_with_lock(self, click_type: ClickTypes, duration: float | None = None, start_time: float | None = None):
        """Handle press event with a lock to ensure sequential execution."""
        now = time.time()
        _LOGGER.debug(
            "[%s] Attempting to acquire lock for event '%s'. Duration: %s", self.name, click_type, now - start_time
        )
        async with self._event_lock:
            _LOGGER.debug(
                "[%s] Acquired lock for event '%s'. Processing...",
                self.name,
                click_type,
            )
            self._last_timestamp = time.time()
            _LOGGER.debug(
                "Press callback: %s on pin %s - %s. Duration: %s",
                click_type,
                self._pin,
                self.name,
                self._last_timestamp - start_time,
            )
            self._last_state = click_type
            await self._manager_press_callback(
                click_type,
                self,
                self._empty_message_after,
                duration,
                start_time,
            )
            event = InputState(
                name=self.name,
                pin=self._pin,
                state=self.last_state,
                type=self.input_type,
                timestamp=self.last_press_timestamp,
                boneio_input=self.boneio_input,
            )
            self._event_bus.trigger_event({
                "event_type": "input", 
                "entity_id": self.id, 
                "event_state": event
            })
        _LOGGER.debug("[%s] Released lock for event '%s'", self.name, click_type)


    def set_actions(self, actions: dict) -> None:
        self._actions = actions

    def get_actions_of_click(self, click_type: ClickTypes) -> dict:
        return self._actions.get(click_type, [])

    @property
    def is_pressed(self) -> bool:
        """Is button pressed."""
        return self.gpio_manager.read(self._pin)

    @property
    def pressed_state(self) -> str:
        """Pressed state for"""
        return self._click_type[0] if self._state else self._click_type[1]

    @property
    def name(self) -> str:
        """Name of the GPIO visible in HA/MQTT."""
        return self._name

    @property
    def pin(self) -> str:
        """Return configured pin."""
        return self._pin

    @property
    def id(self) -> str:
        return self._pin

    @property
    def last_state(self) -> str:
        return self._last_state

    @property
    def input_type(self) -> str:
        return self._input_type

    @property
    def last_press_timestamp(self) -> float:
        return self._last_timestamp
