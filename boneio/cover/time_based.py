from __future__ import annotations

import asyncio
import logging
import time

from boneio.const import (
    IDLE,
    OPENING,
)
from boneio.cover.cover import BaseCover
from boneio.helper.events import async_call_later_miliseconds
from boneio.models import CoverState

_LOGGER = logging.getLogger(__name__)
COVER_MOVE_UPDATE_INTERVAL = 50  # ms
DEFAULT_RESTORED_STATE = {"position": 100}

class TimeBasedCover(BaseCover):
    """Time-based cover algorithm similar to ESPHome."""
    def __init__(
        self,
        restored_state: dict = DEFAULT_RESTORED_STATE,
        **kwargs,
    ) -> None:
        position = float(restored_state.get("position", DEFAULT_RESTORED_STATE["position"]))
        super().__init__(
            position=position,
            **kwargs,
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
    def kind(self) -> str:
        return "time"

    def update_config_times(self, config: dict) -> None:
        self._open_duration = config.get("open_duration", self._open_duration)
        self._close_duration = config.get("close_duration", self._close_duration)
    