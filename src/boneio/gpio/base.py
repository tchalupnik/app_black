from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal, TypeAlias

import anyio.abc

from boneio.config import (
    ActionConfig,
    BinarySensorActionTypes,
    BoneIOInput,
    EventActionTypes,
)
from boneio.events import EventBus, InputEvent
from boneio.gpio_manager import GpioManagerBase
from boneio.models import InputState

_LOGGER = logging.getLogger(__name__)

ClickTypes: TypeAlias = Literal["single", "double", "long", "pressed", "released"]


@dataclass(kw_only=True)
class GpioBase:
    """Base class for initialize GPIO"""

    pin: str
    name: str
    tg: anyio.abc.TaskGroup
    gpio_manager: GpioManagerBase
    event_bus: EventBus
    input_type: str
    actions: dict[EventActionTypes | BinarySensorActionTypes, list[ActionConfig]]
    empty_message_after: bool
    manager_press_callback: Callable[
        [ClickTypes, GpioBase, str, bool, float | None],
        Coroutine[Any, Any, None],
    ]

    gpio_mode: Literal["gpio", "gpio_pu", "gpio_pd", "gpio_input"] = "gpio"
    boneio_input: BoneIOInput | None = None
    bounce_time: timedelta = timedelta(milliseconds=50)

    click_type: (
        tuple[Literal["pressed"], Literal["released"]]
        | tuple[Literal["released"], Literal["pressed"]]
    ) = field(default_factory=lambda: ("pressed", "released"), init=False)
    event_lock: anyio.Lock = field(default_factory=anyio.Lock, init=False)
    last_state: str = field(default="Unknown", init=False)
    last_press_timestamp: float = field(default=0.0, init=False)
    state: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        """Setup GPIO Input Button"""
        self.gpio_manager.init(pin=self.pin, mode="in", pull_mode=self.gpio_mode)

    def press_callback(
        self,
        click_type: ClickTypes,
        duration: float | None = None,
        start_time: float | None = None,
    ) -> None:
        """Handle press callback."""
        self.tg.start_soon(
            self._handle_press_with_lock, click_type, duration, start_time
        )

    async def _handle_press_with_lock(
        self,
        click_type: ClickTypes,
        duration: float | None = None,
        start_time: float | None = None,
    ) -> None:
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
        async with self.event_lock:
            _LOGGER.debug(
                "[%s] Acquired lock for event '%s'. Processing...",
                self.name,
                click_type,
            )
            self.last_press_timestamp = time.time()
            if start_time is None:
                _LOGGER.debug(
                    "Press callback: %s on pin %s - %s.",
                    click_type,
                    self.pin,
                    self.name,
                )
            else:
                _LOGGER.debug(
                    "Press callback: %s on pin %s - %s. Duration: %s",
                    click_type,
                    self.pin,
                    self.name,
                    duration,
                )
            self.last_state = click_type
            await self.manager_press_callback(
                click_type,
                self,
                self.empty_message_after,
                duration,
                start_time,
            )
            self.event_bus.trigger_event(
                InputEvent(
                    entity_id=self.pin,
                    event_state=InputState(
                        name=self.name,
                        pin=self.pin,
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
        return self.click_type[0] if self.state else self.click_type[1]
