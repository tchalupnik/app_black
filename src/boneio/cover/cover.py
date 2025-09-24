from __future__ import annotations

import asyncio
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING

from boneio.const import COVER
from boneio.events import CoverEvent, EventBus
from boneio.helper.state_manager import CoverStateEntry
from boneio.helper.util import strip_accents
from boneio.models import CoverState, CoverStateOperation, CoverStateState
from boneio.relay import MCPRelay

if TYPE_CHECKING:
    from boneio.message_bus.basic import MessageBus

_LOGGER = logging.getLogger(__name__)


class BaseCoverABC(ABC):
    """Base cover class."""

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

    @abstractmethod
    async def run_cover(
        self,
        current_operation: CoverStateOperation,
        target_position: float | None = None,
        target_tilt: float | None = None,
    ) -> None:
        """This function is called to run cover after calling open, close, toggle, toggle_open, toggle_close, set_cover_position"""

    @abstractmethod
    async def send_state(self) -> None:
        pass


class BaseCover(BaseCoverABC):
    def __init__(
        self,
        id: str,
        open_relay: MCPRelay,
        close_relay: MCPRelay,
        state_save: Callable[[CoverStateEntry], None],
        open_time: timedelta,
        close_time: timedelta,
        event_bus: EventBus,
        message_bus: MessageBus,
        topic_prefix: str,
        position: int,
    ) -> None:
        self.id = id.replace(" ", "")
        self.name = id
        self.message_bus = message_bus
        self._send_topic = f"{topic_prefix}/{COVER}/{strip_accents(self.id)}"
        self._loop = asyncio.get_event_loop()
        self._open_relay = open_relay
        self._close_relay = close_relay
        self._state_save = state_save
        self._event_bus = event_bus
        self._open_time = open_time.total_seconds() * 1000
        self._close_time = close_time.total_seconds() * 1000
        self.position = position
        self.tilt: int = 0
        self._initial_position = None
        self.current_operation = CoverStateOperation.IDLE

        self.timestamp = time.monotonic()

        self._last_update_time = 0
        self._closed = position <= 0

        self._movement_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._event_bus.add_sigterm_listener(self.on_exit)

        self._loop.call_soon_threadsafe(self._loop.call_later, 0.5, self.send_state)

    async def on_exit(self) -> None:
        """Stop on exit."""
        await self.stop(on_exit=True)

    async def stop(self, on_exit=False) -> None:
        if self._movement_thread and self._movement_thread.is_alive():
            self._stop_event.set()
            self._movement_thread.join(timeout=0.5)
            self._open_relay.turn_off()
            self._close_relay.turn_off()
            self.current_operation = CoverStateOperation.IDLE
            if not on_exit:
                self.send_state()

    async def open(self) -> None:
        if self.position >= 100:
            return
        _LOGGER.info("Opening cover %s.", self.id)
        await self.run_cover(current_operation=CoverStateOperation.OPENING)
        self.message_bus.send_message(
            topic=f"{self._send_topic}/state", payload=CoverStateState.OPENING.value
        )

    async def close(self) -> None:
        if self.position <= 0:
            return
        _LOGGER.info("Closing cover %s.", self.id)
        await self.run_cover(current_operation=CoverStateOperation.CLOSING)
        self.message_bus.send_message(
            topic=f"{self._send_topic}/state", payload=CoverStateState.CLOSING.value
        )

    async def set_cover_position(self, position: int) -> None:
        if not 0 <= position <= 100:
            raise ValueError("Pozycja musi być w zakresie od 0 do 100.")

        if abs(self.position - position) < 1:
            return

        if position > self.position:
            await self.run_cover(
                current_operation=CoverStateOperation.OPENING, target_position=position
            )
        elif position < self.position:
            await self.run_cover(
                current_operation=CoverStateOperation.CLOSING, target_position=position
            )

    async def toggle(self) -> None:
        _LOGGER.debug("Toggle cover %s from input.", self.id)
        if self.position > 50:
            await self.close()
        else:
            await self.open()

    async def toggle_open(self) -> None:
        _LOGGER.debug("Toggle open cover %s from input.", self.id)
        if self.current_operation != CoverStateOperation.IDLE:
            await self.stop()
        else:
            await self.open()

    async def toggle_close(self) -> None:
        _LOGGER.debug("Toggle close cover %s from input.", self.id)
        if self.current_operation != CoverStateOperation.IDLE:
            await self.stop()
        else:
            await self.close()

    @property
    def state(self) -> CoverStateState:
        if self.current_operation == CoverStateOperation.OPENING:
            return CoverStateState.OPENING
        elif self.current_operation == CoverStateOperation.CLOSING:
            return CoverStateState.CLOSING
        else:
            return (
                CoverStateState.CLOSED if self.position == 0 else CoverStateState.OPEN
            )

    def send_state(self) -> None:
        self._event_bus.trigger_event(
            CoverEvent(
                entity_id=self.id,
                event_state=CoverState(
                    id=self.id,
                    name=self.name,
                    state=self.state,
                    timestamp=self.timestamp,
                    current_operation=self.current_operation,
                    position=self.position,
                    tilt=self.tilt,
                ),
            )
        )
        self.message_bus.send_message(
            topic=f"{self._send_topic}/state", payload=self.state.value
        )
        self.message_bus.send_message(
            topic=f"{self._send_topic}/pos",
            payload={"position": self.position, "tilt": self.tilt},
        )

    def send_state_and_save(self) -> None:
        self.send_state()
        self._state_save(CoverStateEntry(position=self.position))
