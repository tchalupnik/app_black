from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from abc import ABC
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, TypeAlias

import anyio
import anyio.abc
from pydantic import BaseModel, Discriminator, Field

from boneio.models import (
    CoverState,
    HostSensorState,
    InputState,
    OutputState,
    SensorState,
)

_LOGGER = logging.getLogger(__name__)
UTC = dt.timezone.utc

EntityId: TypeAlias = str
ListenerId: TypeAlias = str


class EventType(Enum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    COVER = "COVER"
    SENSOR = "SENSOR"
    MODBUS_DEVICE = "MODBUS_DEVICE"
    HOST = "HOST"


class BaseEvent(BaseModel, ABC):
    """Base event model that all events should inherit from."""

    event_type: EventType
    entity_id: EntityId

    class Config:
        """Pydantic configuration."""

        frozen = True  # Make events immutable


class InputEvent(BaseEvent):
    """Event for input state changes."""

    event_type: Literal[EventType.INPUT] = EventType.INPUT
    event_state: InputState


class OutputEvent(BaseEvent):
    """Event for output state changes."""

    event_type: Literal[EventType.OUTPUT] = EventType.OUTPUT
    event_state: OutputState


class CoverEvent(BaseEvent):
    """Event for cover state changes."""

    event_type: Literal[EventType.COVER] = EventType.COVER
    event_state: CoverState


class SensorEvent(BaseEvent):
    """Event for sensor state changes."""

    event_type: Literal[EventType.SENSOR] = EventType.SENSOR
    event_state: SensorState


class ModbusDeviceEvent(BaseEvent):
    """Event for modbus device state changes."""

    event_type: Literal[EventType.MODBUS_DEVICE] = EventType.MODBUS_DEVICE
    event_state: SensorState


class HostEvent(BaseEvent):
    """Event for host system state changes."""

    event_type: Literal[EventType.HOST] = EventType.HOST
    event_state: HostSensorState


Event = Annotated[
    (
        InputEvent
        | OutputEvent
        | CoverEvent
        | SensorEvent
        | ModbusDeviceEvent
        | HostEvent
    ),
    Discriminator("event_type"),
]


def utcnow() -> dt.datetime:
    return dt.datetime.now(UTC)


def _async_create_timer(
    tg: anyio.abc.TaskGroup, event_callback: Callable[[], None]
) -> None:
    """Create a timer that will start on BoneIO start."""
    handle = None

    def schedule_tick(now: dt.datetime) -> None:
        """Schedule a timer tick when the next second rolls around."""
        nonlocal handle
        slp_seconds = 1 - (now.microsecond / 10**6)
        handle = tg.start_soon(slp_seconds, fire_time_event)

    def fire_time_event() -> None:
        """Fire next time event."""
        now = utcnow()
        event_callback()
        schedule_tick(now)

    def stop_timer() -> None:
        """Stop the timer."""
        if handle is not None:
            handle.cancel()

    schedule_tick(utcnow())
    return stop_timer


class ListenerJob:
    """Listener to represent jobs during runtime."""

    def __init__(self, target: Callable[..., Coroutine[Any, Any, None] | None]) -> None:
        """Initialize listener."""
        self.target = target

    def set_target(
        self, target: Callable[..., Coroutine[Any, Any, None] | None]
    ) -> None:
        """Set target."""
        self.target = target


class EventBus(BaseModel):
    """
    Simple event bus with async queue for multiple event types.
    """

    _tg: anyio.abc.TaskGroup

    _shutting_down: bool = Field(False, init=False)
    _event_queue: asyncio.Queue[Event] = Field(
        default_factory=lambda: asyncio.Queue(), init=False
    )
    _listener_id_index: dict[str, list[tuple[EventType, str]]] = Field(
        default_factory=dict, init=False
    )
    _every_second_listeners: dict[str, ListenerJob] = Field(
        default_factory=dict, init=False
    )
    _sigterm_listeners: list[Callable[[], Coroutine[Any, Any, None] | None]] = Field(
        default_factory=list, init=False
    )
    _haonline_listeners: list[Callable[[], None]] = Field(
        default_factory=list, init=False
    )
    _event_listeners: dict[EventType, dict[EntityId, dict[ListenerId, ListenerJob]]] = (
        Field(
            default_factory=lambda: {
                EventType.INPUT: {},
                EventType.OUTPUT: {},
                EventType.COVER: {},
                EventType.MODBUS_DEVICE: {},
                EventType.SENSOR: {},
                EventType.HOST: {},
            },
            init=False,
        )
    )

    @classmethod
    @asynccontextmanager
    async def create(cls) -> AsyncGenerator[EventBus]:
        async with anyio.create_task_group() as tg:
            this = cls(tg)
            tg.start_soon(this._event_worker)
            _async_create_timer(tg, this._run_second_event)
            _LOGGER.info("Event bus worker started.")
            yield this

    async def _event_worker(self) -> None:
        """
        Background task to process events from the queue.
        """
        while not self._shutting_down:
            try:
                event = await self._event_queue.get()
            except asyncio.CancelledError:
                _LOGGER.info("Event bus worker cancelled.")
                await self.stop()
                raise
            try:
                await self._handle_event(event)
            except Exception as exc:
                _LOGGER.error("Error handling event: %s", exc)
            finally:
                self._event_queue.task_done()

    async def _handle_event(self, event: Event) -> None:
        """
        Dispatch event to registered listeners.
        :param event: BaseEvent model
        """
        entity_id_listeners = self._event_listeners.get(event.event_type, {}).get(
            event.entity_id, {}
        )
        for listener in entity_id_listeners.values():
            try:
                if asyncio.iscoroutinefunction(listener.target):
                    await listener.target(event.event_state)
                else:
                    listener.target(event.event_state)
            except Exception as exc:
                _LOGGER.error("Listener error: %s", exc)

    def trigger_event(self, event: Event) -> None:
        """
        Put event into the queue for async processing.
        :param event: Event model
        """
        self._event_queue.put_nowait(event)

    def request_stop(self) -> None:
        """Request the event bus to stop."""
        if not self._shutting_down:
            self._shutting_down = True
            self._tg.cancel_scope.cancel()

    async def stop(self) -> None:
        """
        Stop the event bus and worker task gracefully.
        """
        if self._shutting_down:
            return
        self._shutting_down = True
        await self._handle_sigterm_listeners()
        for listener in self._every_second_listeners.values():
            listener.target(None)
        self._tg.cancel_scope.cancel()
        _LOGGER.info("Shutdown EventBus gracefully.")

    def _run_second_event(self) -> None:
        """Run event every second."""
        for listener in self._every_second_listeners.values():
            self._tg.start_soon(listener.target)

    async def _handle_sigterm_listeners(self) -> None:
        """Handle all sigterm listeners, supporting both async and sync listeners."""
        for target in self._sigterm_listeners:
            try:
                _LOGGER.debug("Invoking sigterm listener %s", target)
                if asyncio.iscoroutinefunction(target):
                    await target()
                else:
                    target()
            except Exception as e:
                _LOGGER.error("Error in sigterm listener %s: %s", target, e)

    def add_every_second_listener(
        self, name: str, target: Callable[[], None]
    ) -> ListenerJob:
        """Add listener on every second job."""
        self._every_second_listeners[name] = ListenerJob(target=target)
        return self._every_second_listeners[name]

    def add_sigterm_listener(
        self, target: Callable[[], Coroutine[Any, Any, None] | None]
    ) -> None:
        """Add sigterm listener."""
        self._sigterm_listeners.append(target)

    def add_event_listener(
        self,
        event_type: EventType,
        entity_id: str,
        listener_id: str,
        target: Callable[[Event], Coroutine[Any, Any, None] | None],
    ) -> ListenerJob | None:
        """Add event listener.

        listener_id is typically group_id for group outputs or ws (websocket)
        """
        if entity_id not in self._event_listeners[event_type]:
            self._event_listeners[event_type][entity_id] = {}
        if listener_id in self._event_listeners[event_type][entity_id]:
            listener = self._event_listeners[event_type][entity_id][listener_id]
            listener.set_target(target)
            return listener

        # Add to main listeners
        listener_job = ListenerJob(target=target)
        self._event_listeners[event_type][entity_id][listener_id] = listener_job

        # Add to index
        if listener_id not in self._listener_id_index:
            self._listener_id_index[listener_id] = []
        self._listener_id_index[listener_id].append((event_type, entity_id))

        return listener_job

    def remove_event_listener(
        self,
        event_type: EventType | None = None,
        entity_id: str | None = None,
        listener_id: str | None = None,
    ) -> None:
        """Remove event listener. Can remove by event_type, listener_id, or both."""
        if listener_id is not None and listener_id in self._listener_id_index:
            # Remove by listener_id
            for evt_type, ent_id in self._listener_id_index[listener_id]:
                if evt_type != event_type or ent_id != entity_id:
                    continue

                if ent_id in self._event_listeners[evt_type]:
                    if listener_id in self._event_listeners[evt_type][ent_id]:
                        del self._event_listeners[evt_type][ent_id][listener_id]
                    if not self._event_listeners[evt_type][ent_id]:
                        del self._event_listeners[evt_type][ent_id]

            if event_type is None and entity_id is None:
                # If removing all references to this listener_id
                del self._listener_id_index[listener_id]
            else:
                # Update index to remove only specific references
                self._listener_id_index[listener_id] = [
                    (evt_type, ent_id)
                    for evt_type, ent_id in self._listener_id_index[listener_id]
                    if (event_type and evt_type != event_type)
                    or (entity_id and ent_id != entity_id)
                ]
                if not self._listener_id_index[listener_id]:
                    del self._listener_id_index[listener_id]

        elif event_type is not None:
            # Remove by event_type
            if entity_id:
                # Remove specific entity
                if entity_id in self._event_listeners[event_type]:
                    for lid in list(
                        self._event_listeners[event_type][entity_id].keys()
                    ):
                        self.remove_event_listener(event_type, entity_id, lid)
                    del self._event_listeners[event_type][entity_id]
            else:
                # Remove entire event_type
                for ent_id in self._event_listeners[event_type].keys():
                    for lid in self._event_listeners[event_type][ent_id].keys():
                        self.remove_event_listener(event_type, ent_id, lid)

    def add_haonline_listener(self, target: Callable[[], None]) -> None:
        """Add HA Online listener."""
        self._haonline_listeners.append(target)

    async def signal_ha_online(self) -> None:
        """Call events if HA goes online."""
        for target in self._haonline_listeners:
            if asyncio.iscoroutinefunction(target):
                await target()
            else:
                target()

    def remove_every_second_listener(self, name: str) -> None:
        """Remove regular listener."""
        if name in self._every_second_listeners:
            del self._every_second_listeners[name]


def _as_utc(dattim: dt.datetime) -> dt.datetime:
    """Return a datetime as UTC time.

    Assumes datetime without tzinfo to be in the DEFAULT_TIME_ZONE.
    """
    if dattim.tzinfo == UTC:
        return dattim
    return dattim.astimezone(UTC)


def async_track_point_in_time(
    loop: asyncio.AbstractEventLoop, job: Any, point_in_time: datetime, **kwargs: Any
) -> Callable[[], None]:
    """Add a listener that fires once after a specific point in UTC time."""
    # Ensure point_in_time is UTC
    utc_point_in_time = _as_utc(point_in_time)
    expected_fire_timestamp = utc_point_in_time.timestamp()

    # Since this is called once, we accept a so we can avoid
    # having to figure out how to call the action every time its called.
    cancel_callback: asyncio.TimerHandle | None = None

    def run_action(job: Callable[..., Coroutine[Any, Any, None] | None]) -> None:
        """Call the action."""
        nonlocal cancel_callback

        # Depending on the available clock support (including timer hardware
        # and the OS kernel) it can happen that we fire a little bit too early
        # as measured by utcnow(). That is bad when callbacks have assumptions
        # about the current time. Thus, we rearm the timer for the remaining
        # time.
        delta = expected_fire_timestamp - time.time()
        if delta > 0:
            _LOGGER.debug("Called %f seconds too early, rearming", delta)

            cancel_callback = loop.call_later(delta, run_action, job)
            return

        if asyncio.iscoroutinefunction(job):
            loop.create_task(job(utc_point_in_time, **kwargs))
        else:
            loop.call_soon(job, utc_point_in_time, **kwargs)

    delta = expected_fire_timestamp - time.time()
    cancel_callback = loop.call_later(delta, run_action, job)

    def unsub_point_in_time_listener() -> None:
        """Cancel the call_later."""
        assert cancel_callback is not None
        cancel_callback.cancel()

    return unsub_point_in_time_listener
