from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from boneio.const import (
    CLOSED,
    CLOSING,
    COVER,
    IDLE,
    OPEN,
    OPENING,
)
from boneio.helper.events import EventBus, async_call_later_miliseconds
from boneio.helper.mqtt import BasicMqtt
from boneio.helper.timeperiod import TimePeriod
from boneio.models import CoverState
from boneio.relay import MCPRelay

_LOGGER = logging.getLogger(__name__)
COVER_MOVE_UPDATE_INTERVAL = 50  # ms
DEFAULT_RESTORED_STATE = {"position": 100}

class TimeBasedCover(BasicMqtt):
    """Time-based cover algorithm similar to ESPHome."""
    def __init__(
        self,
        id: str,
        open_relay: MCPRelay,
        close_relay: MCPRelay,
        state_save: Callable,
        open_time: TimePeriod,
        close_time: TimePeriod,
        event_bus: EventBus,
        restored_state: dict = DEFAULT_RESTORED_STATE,
        **kwargs,
    ) -> None:
        super().__init__(id=id, name=id, topic_type=COVER, **kwargs)
        self._loop = asyncio.get_event_loop()
        self._id = id
        self._open_relay = open_relay
        self._close_relay = close_relay
        self._state_save = state_save
        self._event_bus = event_bus
        self._open_duration = open_time.total_milliseconds
        self._close_duration = close_time.total_milliseconds
        self._position = float(restored_state.get("position", DEFAULT_RESTORED_STATE["position"]))
        self._current_operation = IDLE
        self._target_position = None
        self._start_time = None
        self._start_position = None
        self._timer_handle = None
        self._last_timestamp = 0.0
        self._last_position_update = 0.0
        self._closed = self._position <= 0
        self._event_bus.add_sigterm_listener(self.on_exit)
        self._loop.call_soon_threadsafe(
            self._loop.call_later, 0.5, self.send_state,
        )

    def _recompute_position(self) -> None:
        if self._current_operation == IDLE or self._start_time is None:
            return
        elapsed = (time.time() - self._start_time) * 1000.0
        duration = self._open_duration if self._current_operation == OPENING else self._close_duration
        if self._current_operation == OPENING:
            delta = (elapsed / duration) * 100.0
            new_position = self._start_position + delta
        else:
            delta = (elapsed / duration) * 100.0
            new_position = self._start_position - delta
        self._position = max(0.0, min(100.0, new_position))

    async def _update_position(self) -> None:
        if self._current_operation == IDLE:
            return
        self._recompute_position()
        now = time.time()
        rounded_pos = round(self._position, 0)
        time_since_last_update = now - self._last_position_update
        is_target = (
            self._target_position is not None and rounded_pos == self._target_position
        ) or (
            self._target_position is None and (rounded_pos >= 100 or rounded_pos <= 0)
        )
        if time_since_last_update >= 1.0 or is_target:
            self.send_position(rounded_pos)
            await self.async_send_state(rounded_pos)
            self._last_position_update = now
        if is_target:
            await self.stop()
        self._closed = self._position <= 0

    async def _handle_cover_update(self) -> None:
        if self._current_operation == IDLE:
            return
        await self._update_position()
        if self._current_operation != IDLE:
            self._timer_handle = async_call_later_miliseconds(
                self._loop,
                lambda _: self._loop.create_task(self._handle_cover_update()),
                COVER_MOVE_UPDATE_INTERVAL
            )

    async def run_cover(self, current_operation: str, target_position: float = None) -> None:
        if self._current_operation != IDLE:
            self._stop_cover()
        self._current_operation = current_operation
        self._target_position = target_position
        self._start_time = time.time()
        self._start_position = self._position
        (relay, other_relay) = (self._open_relay, self._close_relay) if current_operation == OPENING else (self._close_relay, self._open_relay)
        async with asyncio.Lock():
            if other_relay.is_active:
                other_relay.turn_off()
            relay.turn_on()
            self._timer_handle = async_call_later_miliseconds(
                self._loop,
                lambda _: self._loop.create_task(self._handle_cover_update()),
                COVER_MOVE_UPDATE_INTERVAL
            )

    def _stop_cover(self, on_exit=False) -> None:
        self._open_relay.turn_off()
        self._close_relay.turn_off()
        if self._timer_handle:
            self._timer_handle()
            self._timer_handle = None
            self._target_position = None
            if not on_exit:
                self.send_state()
        self._current_operation = IDLE

    async def stop(self) -> None:
        _LOGGER.info("Stopping cover %s.", self._id)
        if self._current_operation != IDLE:
            self._stop_cover()
        await self.async_send_state()

    def on_exit(self) -> None:
        self._stop_cover(on_exit=True)

    async def open(self) -> None:
        if self._position >= 100:
            return
        _LOGGER.info("Opening cover %s.", self._id)
        await self.run_cover(OPENING)
        self._send_message(topic=f"{self._send_topic}/state", payload=OPENING)

    async def close(self) -> None:
        if self._position <= 0:
            return
        _LOGGER.info("Closing cover %s.", self._id)
        await self.run_cover(CLOSING)
        self._send_message(topic=f"{self._send_topic}/state", payload=CLOSING)

    async def set_cover_position(self, position: int) -> None:
        set_position = round(position, 0)
        if self._position == set_position:
            return
        if self._target_position is not None:
            self._stop_cover()
        _LOGGER.info("Setting cover at position %s.", set_position)
        self._target_position = set_position
        direction = CLOSING if set_position < self._position else OPENING
        self._send_message(topic=f"{self._send_topic}/state", payload=direction)
        await self.run_cover(direction, target_position=set_position)

    async def async_send_state(self, position: int | None = None) -> None:
        self._last_timestamp = time.time()
        position = position or round(self._position, 0)
        event = CoverState(
            id=self.id,
            name=self.name,
            state=self.state,
            position=position,
            kind=self.kind,
            timestamp=self._last_timestamp,
            current_operation=self._current_operation,
        )
        await self._event_bus.async_trigger_event(event_type="cover", entity_id=self.id, event=event)

    def send_position(self, position: float) -> None:
        self._send_message(topic=f"{self._send_topic}/pos", payload={ "position": str(position) })

    def send_state(self) -> None:
        self._send_message(topic=f"{self._send_topic}/state", payload=self.state)
        pos = round(self._position, 0)
        self.send_position(pos)
        self._state_save(value={"position": pos})

    @property
    def state(self) -> str:
        return CLOSED if self._closed else OPEN

    @property
    def position(self) -> float:
        return round(self._position, 0)

    @property
    def current_operation(self) -> str:
        return self._current_operation

    @property
    def last_timestamp(self) -> float:
        return self._last_timestamp

    @property
    def kind(self) -> str:
        return "time"
    