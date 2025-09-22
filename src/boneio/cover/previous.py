"""Cover module."""

from __future__ import annotations

import asyncio
import logging
import time
import typing
from collections.abc import Callable
from datetime import timedelta

from boneio.config import CoverConfig
from boneio.const import COVER
from boneio.helper.events import EventBus
from boneio.helper.state_manager import CoverStateEntry
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


class PreviousCover:
    """Cover class of boneIO"""

    def __init__(
        self,
        id: str,
        config: CoverConfig,
        open_relay: BasicRelay,
        close_relay: BasicRelay,
        state_save: Callable[[CoverStateEntry], None],
        event_bus: EventBus,
        message_bus: MessageBus,
        topic_prefix: str,
        restored_state: CoverStateEntry,
    ) -> None:
        """Initialize cover class."""
        self._loop = asyncio.get_event_loop()
        self.id = id.replace(" ", "")
        self.name = id
        self.message_bus = message_bus
        self._send_topic = f"{topic_prefix}/{COVER}/{strip_accents(self.id)}"
        self._lock = asyncio.Lock()
        self._state_save = state_save
        self._open = RelayHelper(relay=open_relay, time=config.open_time)
        self._close = RelayHelper(relay=close_relay, time=config.close_time)
        self._set_position = None
        self.current_operation = CoverStateOperation.IDLE
        self._position = restored_state.position
        self._requested_closing = True
        self._event_bus = event_bus
        self._timer_handle = None
        self.timestamp = 0.0
        self.tilt = None
        self.state = (
            CoverStateState.CLOSED if self._position == 0 else CoverStateState.OPEN
        )
        self._event_bus.add_sigterm_listener(self.on_exit)
        self._loop.call_soon_threadsafe(
            self._loop.call_later,
            0.5,
            self.send_state,
        )

    async def run_cover(self, current_operation: CoverStateOperation) -> None:
        """Run cover engine."""
        if self.current_operation != CoverStateOperation.IDLE:
            self._stop_cover()
        self.current_operation = current_operation

        def get_relays() -> tuple[BasicRelay, BasicRelay]:
            if current_operation == CoverStateOperation.OPENING:
                return (self._open.relay, self._close.relay)
            else:
                return (self._close.relay, self._open.relay)

        (relay, inverted_relay) = get_relays()
        async with self._lock:
            if inverted_relay.is_active:
                inverted_relay.turn_off()
            self._timer_handle = self._event_bus.add_every_second_listener(
                f"{COVER}{self.id}", self.listen_cover
            )
            relay.turn_on()

    def on_exit(self) -> None:
        """Stop on exit."""
        self._stop_cover(on_exit=True)

    async def stop(self) -> None:
        """Public Stop cover graceful."""
        _LOGGER.info("Stopping cover %s.", self.name)
        if self.current_operation != CoverStateOperation.IDLE:
            self._stop_cover(on_exit=False)
        await self.async_send_state()

    async def async_send_state(self) -> None:
        """Send state to Websocket on action asynchronously."""
        self.timestamp = time.time()
        event = CoverState(
            id=self.id,
            name=self.name,
            state=self.state,
            position=round(self._position, 0),
            timestamp=self.timestamp,
            current_operation=self.current_operation,
        )
        self._event_bus.trigger_event(
            {"event_type": "cover", "entity_id": self.id, "event_state": event}
        )

    def send_state(self) -> None:
        """Send state of cover to mqtt."""
        self.message_bus.send_message(
            topic=f"{self._send_topic}/state", payload=self.state.value
        )
        pos = round(self._position, 0)
        self.message_bus.send_message(
            topic=f"{self._send_topic}/pos", payload={"position": str(pos)}
        )
        self._state_save(CoverStateEntry(position=pos))

    def _stop_cover(self, on_exit=False) -> None:
        """Stop cover."""
        self._open.relay.turn_off()
        self._close.relay.turn_off()
        if self._timer_handle is not None:
            self._event_bus.remove_every_second_listener(f"{COVER}{self.id}")
            self._timer_handle = None
            self._set_position = None
            if not on_exit:
                self.send_state()
        self.current_operation = CoverStateOperation.IDLE

    def listen_cover(self) -> None:
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
        self._position += step
        rounded_pos = round(self._position, 0)
        if self._set_position:
            # Set position is only working for every 10%, so round to nearest 10.
            # Except for start moving time
            if (self._requested_closing and rounded_pos < 95) or rounded_pos > 5:
                rounded_pos = round(self._position, -1)
        else:
            if rounded_pos > 100:
                rounded_pos = 100
            elif rounded_pos < 0:
                rounded_pos = 0
        self.message_bus.send_message(
            topic=f"{self._send_topic}/pos", payload={"position": str(rounded_pos)}
        )
        asyncio.create_task(self.async_send_state())
        self.state = (
            CoverStateState.CLOSED if self._position <= 0 else CoverStateState.OPEN
        )
        if rounded_pos == self._set_position or (
            self._set_position is None and (rounded_pos >= 100 or rounded_pos <= 0)
        ):
            self._position = rounded_pos
            self._stop_cover()

    async def close_cover(self) -> None:
        """Close cover."""
        if self._position == 0:
            return
        if self._position is None:
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
        if self._position == 100:
            return
        if self._position is None:
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
        if self._position == position or set_position == self._set_position:
            return
        if self._set_position:
            self._stop_cover(on_exit=True)
        _LOGGER.info("Setting cover at position %s.", set_position)
        self._set_position = set_position

        self._requested_closing = set_position < self._position
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
