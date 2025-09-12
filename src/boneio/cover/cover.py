from __future__ import annotations

import asyncio
import logging
import threading
import time
import typing
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import timedelta

from boneio.const import (
    CLOSED,
    CLOSING,
    COVER,
    IDLE,
    OPEN,
    OPENING,
)
from boneio.helper.events import EventBus
from boneio.helper.mqtt import BasicMqtt
from boneio.models import CoverState, PositionDict
from boneio.relay import MCPRelay

if typing.TYPE_CHECKING:
    from boneio.message_bus.basic import MessageBus

_LOGGER = logging.getLogger(__name__)


class BaseCoverABC(ABC):
    """Base cover class."""

    @abstractmethod
    def __init__(
        self,
        id: str,
        open_relay: MCPRelay,
        close_relay: MCPRelay,
        state_save: Callable,
        open_time: timedelta,
        close_time: timedelta,
        event_bus: EventBus,
        message_bus: MessageBus,
        topic_prefix: str,
        position: int = 100,
    ) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop cover."""

    @abstractmethod
    async def open(self) -> None:
        """Open cover."""

    @abstractmethod
    async def close(self) -> None:
        """Close cover."""

    @abstractmethod
    async def toggle(self) -> None:
        """Toggle cover to open or close."""

    @abstractmethod
    async def toggle_open(self) -> None:
        """Toggle cover to open or stop."""

    @abstractmethod
    async def toggle_close(self) -> None:
        """Toggle cover to close or stop."""

    @abstractmethod
    async def set_cover_position(self, position: int) -> None:
        """Set cover position."""

    @property
    @abstractmethod
    def state(self) -> str:
        pass

    @property
    @abstractmethod
    def position(self) -> int:
        pass

    @property
    @abstractmethod
    def current_operation(self) -> str:
        pass

    @property
    @abstractmethod
    def last_timestamp(self) -> float:
        pass

    @abstractmethod
    async def run_cover(
        self,
        current_operation: str,
        target_position: float | None = None,
        target_tilt: float | None = None,
    ) -> None:
        """This function is called to run cover after calling open, close, toggle, toggle_open, toggle_close, set_cover_position"""

    @abstractmethod
    async def send_state(self, state: str, position: float) -> None:
        pass


class BaseVenetianCoverABC:
    @property
    @abstractmethod
    def tilt_position(self) -> int:
        pass

    @property
    @abstractmethod
    def tilt_current_operation(self) -> str:
        pass

    @property
    @abstractmethod
    def last_tilt_timestamp(self) -> float:
        pass

    @abstractmethod
    async def set_cover_tilt_position(self, position: int) -> None:
        """Set cover tilt position."""

    @abstractmethod
    async def tilt_open(self) -> None:
        """Open cover tilt."""

    @abstractmethod
    async def tilt_close(self) -> None:
        """Close cover tilt."""


class BaseCover(BaseCoverABC, BasicMqtt):
    def __init__(
        self,
        id: str,
        open_relay: MCPRelay,
        close_relay: MCPRelay,
        state_save: Callable,
        open_time: timedelta,
        close_time: timedelta,
        event_bus: EventBus,
        message_bus: MessageBus,
        topic_prefix: str,
        position: int = 100,
    ) -> None:
        BasicMqtt.__init__(
            self,
            id=id,
            name=id,
            topic_type=COVER,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
        )
        self._loop = asyncio.get_event_loop()
        self._id = id
        self._open_relay = open_relay
        self._close_relay = close_relay
        self._state_save = state_save
        self._event_bus = event_bus
        self._open_time = open_time.total_seconds() * 1000
        self._close_time = close_time.total_seconds() * 1000
        self._position = position
        self._initial_position = None
        self.current_operation = IDLE

        self.last_timestamp = time.monotonic()

        self._last_update_time = 0
        self._closed = position <= 0

        self._movement_thread = None
        self._stop_event = threading.Event()

        self._event_bus.add_sigterm_listener(self.on_exit)

        self._loop.call_soon_threadsafe(
            self._loop.call_later, 0.5, self.send_state, self.state, self.json_position
        )

    async def on_exit(self) -> None:
        """Stop on exit."""
        await self.stop(on_exit=True)

    async def stop(self, on_exit=False) -> None:
        if self._movement_thread and self._movement_thread.is_alive():
            self._stop_event.set()
            self._movement_thread.join(timeout=0.5)
            self._open_relay.turn_off()
            self._close_relay.turn_off()
            self.current_operation = IDLE
            if not on_exit:
                self.send_state(self.state, self.json_position)

    async def open(self) -> None:
        if self._position >= 100:
            return
        _LOGGER.info("Opening cover %s.", self._id)
        await self.run_cover(current_operation=OPENING)
        self.message_bus.send_message(
            topic=f"{self._send_topic}/state", payload=OPENING
        )

    async def close(self) -> None:
        if self._position <= 0:
            return
        _LOGGER.info("Closing cover %s.", self._id)
        await self.run_cover(current_operation=CLOSING)
        self.message_bus.send_message(
            topic=f"{self._send_topic}/state", payload=CLOSING
        )

    async def set_cover_position(self, position: int) -> None:
        if not 0 <= position <= 100:
            raise ValueError("Pozycja musi być w zakresie od 0 do 100.")

        if abs(self._position - position) < 1:
            return

        if position > self._position:
            await self.run_cover(current_operation=OPENING, target_position=position)
        elif position < self._position:
            await self.run_cover(current_operation=CLOSING, target_position=position)

    async def toggle(self) -> None:
        _LOGGER.debug("Toggle cover %s from input.", self._id)
        if self._position > 50:
            await self.close()
        else:
            await self.open()

    async def toggle_open(self) -> None:
        _LOGGER.debug("Toggle open cover %s from input.", self._id)
        if self.current_operation != IDLE:
            await self.stop()
        else:
            await self.open()

    async def toggle_close(self) -> None:
        _LOGGER.debug("Toggle close cover %s from input.", self._id)
        if self.current_operation != IDLE:
            await self.stop()
        else:
            await self.close()

    @property
    def state(self) -> str:
        if self.current_operation == OPENING:
            return OPENING
        elif self.current_operation == CLOSING:
            return CLOSING
        else:
            return CLOSED if self._position == 0 else OPEN

    @property
    def position(self) -> int:
        return round(self._position, 0)

    @property
    def json_position(self) -> PositionDict:
        return {"position": self.position}

    def send_state(self, state: str, json_position: PositionDict) -> None:
        event = CoverState(
            id=self.id,
            name=self.name,
            state=state,
            kind=self.kind,
            timestamp=self.last_timestamp,
            current_operation=self.current_operation,
            position=json_position["position"],
            tilt=json_position["tilt"],
        )
        self._event_bus.trigger_event(
            {"event_type": "cover", "entity_id": self.id, "event_state": event}
        )
        self.message_bus.send_message(topic=f"{self._send_topic}/state", payload=state)
        self.message_bus.send_message(
            topic=f"{self._send_topic}/pos", payload=json_position
        )

    def send_state_and_save(self, json_position: PositionDict):
        self.send_state(self.state, json_position)
        self._state_save(json_position)
