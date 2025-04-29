from __future__ import annotations

import asyncio
import logging
from typing import Callable

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
from boneio.helper.timeperiod import TimePeriod
from boneio.relay import MCPRelay

_LOGGER = logging.getLogger(__name__)

class BaseCover(BasicMqtt):
    def __init__(self, id: str,
        open_relay: MCPRelay,
        close_relay: MCPRelay,
        state_save: Callable,
        open_time: TimePeriod,
        close_time: TimePeriod,
        event_bus: EventBus,
        position: int = 100,
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
        self._position = position
        self._current_operation = IDLE
        self._target_position = None
        self._start_time = None
        self._start_position = None
        self._timer_handle = None
        self._last_timestamp = 0.0
        self._last_position_update = 0.0
        self._closed = position <= 0
        self._event_bus.add_sigterm_listener(self.on_exit)
        self._loop.call_soon_threadsafe(
            self._loop.call_later, 0.5, self.send_state,
        )

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
        direction = CLOSING if set_position < self._position else OPENING
        self._send_message(topic=f"{self._send_topic}/state", payload=direction)
        await self.run_cover(direction, target_position=set_position)

    async def toggle(self) -> None:
        _LOGGER.debug("Toggle cover %s from input.", self._id)
        if self.state == CLOSED:
            await self.close()
        else:
            await self.open()

    async def toggle_open(self) -> None:
        _LOGGER.debug("Toggle open cover %s from input.", self._id)
        if self._current_operation != IDLE:
            await self.stop()
        else:
            await self.open()

    async def toggle_close(self) -> None:
        _LOGGER.debug("Toggle close cover %s from input.", self._id)
        if self._current_operation != IDLE:
            await self.stop()
        else:
            await self.close()


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