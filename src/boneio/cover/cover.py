from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

import anyio

from boneio.events import CoverEvent, EventBus
from boneio.helper.state_manager import CoverStateEntry, StateManager
from boneio.helper.util import strip_accents
from boneio.models import CoverState, CoverStateOperation, CoverStateState
from boneio.relay.basic import BasicRelay

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
        target_position: int | None = None,
        target_tilt: int | None = None,
    ) -> None:
        """This function is called to run cover after calling open, close, toggle, toggle_open, toggle_close, set_cover_position"""

    @abstractmethod
    def send_state(self) -> None:
        pass


@dataclass
class BaseCover(BaseCoverABC):
    id: str
    name: str
    open_relay: BasicRelay
    close_relay: BasicRelay
    state_manager: StateManager
    open_time: timedelta
    close_time: timedelta
    event_bus: EventBus
    message_bus: MessageBus
    topic_prefix: str
    restore_state: bool

    timestamp: float = field(init=False, default_factory=time.monotonic)
    stop_event: anyio.Event = field(init=False)
    current_operation: CoverStateOperation = CoverStateOperation.IDLE
    position: int = 0
    tilt: int = 0

    def __post_init__(self) -> None:
        state = self.state_manager.state.cover.get(self.id)
        if state is not None:
            self.position = state.position
            if state.tilt is not None:
                self.tilt = state.tilt

        self.id = self.id.replace(" ", "")
        self.send_topic = f"{self.topic_prefix}/cover/{strip_accents(self.id)}"
        self.event_bus.add_sigterm_listener(self.on_exit)
        self.send_state()

    async def on_exit(self) -> None:
        """Stop on exit."""
        await self.stop(on_exit=True)

    async def stop(self, on_exit: bool = False) -> None:
        self.stop_event.set()
        async with anyio.create_task_group() as tg:
            tg.start_soon(self.open_relay.turn_off)
            tg.start_soon(self.close_relay.turn_off)
        self.current_operation = CoverStateOperation.IDLE
        if not on_exit:
            self.send_state()

    async def open(self) -> None:
        if self.position >= 100:
            return
        _LOGGER.info("Opening cover %s.", self.id)
        await self.run_cover(current_operation=CoverStateOperation.OPENING)
        self.message_bus.send_message(
            topic=f"{self.send_topic}/state", payload=CoverStateState.OPENING.value
        )

    async def close(self) -> None:
        if self.position <= 0:
            return
        _LOGGER.info("Closing cover %s.", self.id)
        await self.run_cover(current_operation=CoverStateOperation.CLOSING)
        self.message_bus.send_message(
            topic=f"{self.send_topic}/state", payload=CoverStateState.CLOSING.value
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
        self.event_bus.trigger_event(
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
            topic=f"{self.send_topic}/state", payload=self.state.value
        )
        self.message_bus.send_message(
            topic=f"{self.send_topic}/pos",
            payload={"position": self.position, "tilt": self.tilt},
        )

    def send_state_and_save(self) -> None:
        self.send_state()
        if self.restore_state:
            self.state_manager.state.cover[self.id] = CoverStateEntry(
                position=self.position
            )
            self.state_manager.save()
