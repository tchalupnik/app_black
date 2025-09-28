"""Cover module."""

from __future__ import annotations

import logging
import time
import typing
from dataclasses import dataclass, field
from datetime import timedelta

import anyio

from boneio.events import CoverEvent, EventBus
from boneio.helper.state_manager import CoverStateEntry, StateManager
from boneio.helper.util import strip_accents
from boneio.models import (
    CoverState,
    CoverStateOperation,
    CoverStateState,
)
from boneio.relay.basic import BasicRelay

if typing.TYPE_CHECKING:
    from boneio.message_bus.basic import MessageBus

_LOGGER = logging.getLogger(__name__)


class RelayHelper:
    """Relay helper for cover either open/close."""

    def __init__(self, relay: BasicRelay, time: timedelta) -> None:
        """Initialize helper."""
        self.relay = relay
        self.steps = 100 / time.total_seconds()


@dataclass()
class PreviousCover:
    """Cover class of boneIO"""

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

    lock: anyio.Lock = field(init=False, default_factory=anyio.Lock)
    timestamp: float = field(init=False, default_factory=time.monotonic)
    current_operation: CoverStateOperation = CoverStateOperation.IDLE
    position: int = 0
    tilt: int = 0

    def __post_init__(self) -> None:
        """Initialize cover class."""
        self._send_topic = f"{self.topic_prefix}/cover/{strip_accents(self.id)}"
        self._open = RelayHelper(relay=self.open_relay, time=self.open_time)
        self._close = RelayHelper(relay=self.close_relay, time=self.close_time)
        self._set_position = None
        self.current_operation = CoverStateOperation.IDLE

        state = self.state_manager.state.cover.get(self.id)
        if state is not None:
            self.position = state.position
            if state.tilt is not None:
                self.tilt = state.tilt
        self._requested_closing = True
        self._timer_handle = None
        self.state = (
            CoverStateState.CLOSED if self.position == 0 else CoverStateState.OPEN
        )
        self.event_bus.add_sigterm_listener(self.on_exit)
        self.send_state()

    async def run_cover(self, current_operation: CoverStateOperation) -> None:
        """Run cover engine."""
        if self.current_operation != CoverStateOperation.IDLE:
            await self._stop_cover()
        self.current_operation = current_operation

        def get_relays() -> tuple[BasicRelay, BasicRelay]:
            if current_operation == CoverStateOperation.OPENING:
                return (self._open.relay, self._close.relay)
            else:
                return (self._close.relay, self._open.relay)

        (relay, inverted_relay) = get_relays()
        async with self.lock:
            if inverted_relay.is_active():
                await inverted_relay.turn_off()
            self._timer_handle = self.event_bus.add_every_second_listener(
                f"cover{self.id}", self.listen_cover
            )
            await relay.turn_on()

    async def on_exit(self) -> None:
        """Stop on exit."""
        await self._stop_cover(on_exit=True)

    async def stop(self) -> None:
        """Public Stop cover graceful."""
        _LOGGER.info("Stopping cover %s.", self.name)
        if self.current_operation != CoverStateOperation.IDLE:
            await self._stop_cover(on_exit=False)
        self.send_cover_state()

    def send_cover_state(self) -> None:
        """Send state to Websocket on action asynchronously."""
        self.timestamp = time.time()
        self.event_bus.trigger_event(
            CoverEvent(
                entity_id=self.id,
                event_state=CoverState(
                    id=self.id,
                    name=self.name,
                    state=self.state,
                    position=round(self.position, 0),
                    timestamp=self.timestamp,
                    current_operation=self.current_operation,
                ),
            )
        )

    def send_state(self) -> None:
        """Send state of cover to mqtt."""
        self.message_bus.send_message(
            topic=f"{self._send_topic}/state", payload=self.state.value
        )
        pos = round(self.position, 0)
        self.message_bus.send_message(
            topic=f"{self._send_topic}/pos", payload={"position": str(pos)}
        )
        self.state_manager.state.cover[self.id] = CoverStateEntry(position=pos)
        self.state_manager.save()

    async def _stop_cover(self, on_exit: bool = False) -> None:
        """Stop cover."""
        await self._open.relay.turn_off()
        await self._close.relay.turn_off()
        if self._timer_handle is not None:
            self.event_bus.remove_every_second_listener(f"cover{self.id}")
            self._timer_handle = None
            self._set_position = None
            if not on_exit:
                self.send_state()
        self.current_operation = CoverStateOperation.IDLE

    async def listen_cover(self) -> None:
        """Listen for change in cover."""
        if self.current_operation == CoverStateOperation.IDLE:
            return

        def get_step() -> float:
            """Get step for current operation."""
            if self._requested_closing:
                return -self._close.steps
            else:
                return self._open.steps

        step = get_step()
        self.position += step
        rounded_pos = round(self.position, 0)
        if self._set_position:
            # Set position is only working for every 10%, so round to nearest 10.
            # Except for start moving time
            if (self._requested_closing and rounded_pos < 95) or rounded_pos > 5:
                rounded_pos = round(self.position, -1)
        else:
            if rounded_pos > 100:
                rounded_pos = 100
            elif rounded_pos < 0:
                rounded_pos = 0
        self.message_bus.send_message(
            topic=f"{self._send_topic}/pos", payload={"position": str(rounded_pos)}
        )
        self.send_cover_state()
        self.state = (
            CoverStateState.CLOSED if self.position <= 0 else CoverStateState.OPEN
        )
        if rounded_pos == self._set_position or (
            self._set_position is None and (rounded_pos >= 100 or rounded_pos <= 0)
        ):
            self.position = rounded_pos
            await self._stop_cover()

    async def close_cover(self) -> None:
        """Close cover."""
        if self.position == 0:
            return
        if self.position is None:
            self.state = CoverStateState.CLOSED
            return
        _LOGGER.info("Closing cover %s.", self.name)

        self._requested_closing = True
        self.message_bus.send_message(
            topic=f"{self._send_topic}/state", payload=CoverStateState.CLOSING.value
        )
        await self.run_cover(
            current_operation=CoverStateOperation.CLOSING,
        )

    async def open_cover(self) -> None:
        """Open cover."""
        if self.position == 100:
            return
        if self.position is None:
            self.state = CoverStateState.OPEN
            return
        _LOGGER.info("Opening cover %s.", self.name)

        self._requested_closing = False
        self.message_bus.send_message(
            topic=f"{self._send_topic}/state", payload=CoverStateState.OPENING.value
        )
        await self.run_cover(
            current_operation=CoverStateOperation.OPENING,
        )

    async def set_cover_position(self, position: int) -> None:
        """Move cover to a specific position."""
        set_position = round(position, -1)
        if self.position == position or set_position == self._set_position:
            return
        if self._set_position:
            await self._stop_cover(on_exit=True)
        _LOGGER.info("Setting cover at position %s.", set_position)
        self._set_position = set_position

        self._requested_closing = set_position < self.position
        current_operation = (
            CoverStateOperation.CLOSING
            if self._requested_closing
            else CoverStateOperation.OPENING
        )
        _LOGGER.debug(
            "Requested set position %s. Operation %s",
            set_position,
            current_operation,
        )
        self.message_bus.send_message(
            topic=f"{self._send_topic}/state", payload=current_operation.value
        )
        await self.run_cover(
            current_operation=current_operation,
        )

    async def open(self) -> None:
        _LOGGER.debug("Opening cover %s.", self.name)
        await self.open_cover()

    async def close(self) -> None:
        _LOGGER.debug("Closing cover %s.", self.name)
        await self.close_cover()

    async def toggle(self) -> None:
        _LOGGER.debug("Toggle cover %s from input.", self.name)
        if self.state == CoverStateState.CLOSED:
            await self.close()
        else:
            await self.open()

    async def toggle_open(self) -> None:
        _LOGGER.debug("Toggle open cover %s from input.", self.name)
        if self.current_operation != CoverStateOperation.IDLE:
            await self.stop()
        else:
            await self.open()

    async def toggle_close(self) -> None:
        _LOGGER.debug("Toggle close cover %s from input.", self.name)
        if self.current_operation != CoverStateOperation.IDLE:
            await self.stop()
        else:
            await self.close()
