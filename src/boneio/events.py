from __future__ import annotations

import asyncio
import logging
from abc import ABC
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, TypeAlias

import anyio
import anyio.abc
from pydantic import BaseModel, Discriminator

from boneio.models import (
    CoverState,
    InputState,
    OutputState,
    SensorState,
)

_LOGGER = logging.getLogger(__name__)

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
    event_state: None = None


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

EventCallback = Callable[[Event], Coroutine[Any, Any, None]]
SigtermCallback = Callable[[], Coroutine[Any, Any, None]]
EverySecondCallback = Callable[[], Coroutine[Any, Any, None]]


async def _async_create_timer(
    tg: anyio.abc.TaskGroup, event_callback: Callable[[], None]
) -> None:
    """Create a timer that will start on BoneIO start."""

    async def schedule_tick(now: datetime) -> None:
        """Schedule a timer tick when the next second rolls around."""
        slp_seconds = 1 - (now.microsecond / 10**6)
        await anyio.sleep(slp_seconds)
        tg.start_soon(fire_time_event)

    async def fire_time_event() -> None:
        """Fire next time event."""
        now = datetime.now(timezone.utc)
        event_callback()
        await schedule_tick(now)

    await schedule_tick(datetime.now(timezone.utc))


@dataclass
class EventBus:
    """
    Simple event bus with async queue for multiple event types.
    """

    tg: anyio.abc.TaskGroup

    event_queue: asyncio.Queue[Event] = field(
        default_factory=lambda: asyncio.Queue(), init=False
    )
    listener_id_index: dict[str, list[tuple[EventType, str]]] = field(
        default_factory=dict, init=False
    )
    every_second_listeners: dict[str, EverySecondCallback] = field(
        default_factory=dict, init=False
    )
    sigterm_listeners: list[SigtermCallback] = field(default_factory=list, init=False)
    haonline_listeners: list[Callable[[], None]] = field(
        default_factory=list, init=False
    )
    event_listeners: dict[
        EventType, dict[EntityId, dict[ListenerId, EventCallback]]
    ] = field(
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

    @classmethod
    @asynccontextmanager
    async def create(cls) -> AsyncGenerator[EventBus]:
        async with anyio.create_task_group() as tg:
            this = cls(tg)
            tg.start_soon(this._event_worker)
            tg.start_soon(_async_create_timer, tg, this._run_second_event)
            _LOGGER.info("Event bus worker started.")
            try:
                yield this
            except BaseException:
                await this._handle_sigterm_listeners()
                tg.cancel_scope.cancel()
                raise

    async def _event_worker(self) -> None:
        """
        Background task to process events from the queue.
        """
        event = await self.event_queue.get()
        try:
            await self._handle_event(event)
        except Exception as exc:
            _LOGGER.error("Error handling event: %s", exc)
        finally:
            self.event_queue.task_done()

    async def _handle_event(self, event: Event) -> None:
        """
        Dispatch event to registered listeners.
        :param event: BaseEvent model
        """
        entity_id_listeners = self.event_listeners.get(event.event_type, {}).get(
            event.entity_id, {}
        )
        for listener in entity_id_listeners.values():
            try:
                await listener(event)
            except Exception as exc:
                _LOGGER.error("Listener error: %s", exc)

    def trigger_event(self, event: Event) -> None:
        """
        Put event into the queue for async processing.
        :param event: Event model
        """
        self.event_queue.put_nowait(event)

    def _run_second_event(self) -> None:
        """Run event every second."""
        for listener in self.every_second_listeners.values():
            self.tg.start_soon(listener)

    async def _handle_sigterm_listeners(self) -> None:
        """Handle all sigterm listeners, supporting both async and sync listeners."""
        _LOGGER.info("Handling SIGTERM listeners...")
        for target in self.sigterm_listeners:
            try:
                _LOGGER.debug("Invoking sigterm listener %s", target)
                await target()
            except Exception as e:
                _LOGGER.error("Error in sigterm listener %s: %s", target, e)

    def add_every_second_listener(self, name: str, target: EverySecondCallback) -> None:
        """Add listener on every second job."""
        self.every_second_listeners[name] = target

    def add_sigterm_listener(self, target: SigtermCallback) -> None:
        """Add sigterm listener."""
        self.sigterm_listeners.append(target)

    def add_event_listener(
        self,
        event_type: EventType,
        entity_id: str,
        listener_id: str,
        target: EventCallback,
    ) -> None:
        """Add event listener.

        listener_id is typically group_id for group outputs or ws (websocket)
        """
        if entity_id not in self.event_listeners[event_type]:
            self.event_listeners[event_type][entity_id] = {}

        # Add to main listeners
        self.event_listeners[event_type][entity_id][listener_id] = target

        # Add to index
        if listener_id not in self.listener_id_index:
            self.listener_id_index[listener_id] = []
        self.listener_id_index[listener_id].append((event_type, entity_id))

    def remove_event_listener(
        self,
        event_type: EventType | None = None,
        entity_id: str | None = None,
        listener_id: str | None = None,
    ) -> None:
        """Remove event listener. Can remove by event_type, listener_id, or both."""
        if listener_id is not None and listener_id in self.listener_id_index:
            # Remove by listener_id
            for evt_type, ent_id in self.listener_id_index[listener_id]:
                if evt_type != event_type or ent_id != entity_id:
                    continue

                if ent_id in self.event_listeners[evt_type]:
                    if listener_id in self.event_listeners[evt_type][ent_id]:
                        del self.event_listeners[evt_type][ent_id][listener_id]
                    if not self.event_listeners[evt_type][ent_id]:
                        del self.event_listeners[evt_type][ent_id]

            if event_type is None and entity_id is None:
                # If removing all references to this listener_id
                del self.listener_id_index[listener_id]
            else:
                # Update index to remove only specific references
                self.listener_id_index[listener_id] = [
                    (evt_type, ent_id)
                    for evt_type, ent_id in self.listener_id_index[listener_id]
                    if (event_type and evt_type != event_type)
                    or (entity_id and ent_id != entity_id)
                ]
                if not self.listener_id_index[listener_id]:
                    del self.listener_id_index[listener_id]

        elif event_type is not None:
            # Remove by event_type
            if entity_id:
                # Remove specific entity
                if entity_id in self.event_listeners[event_type]:
                    for lid in list(self.event_listeners[event_type][entity_id].keys()):
                        self.remove_event_listener(event_type, entity_id, lid)
                    del self.event_listeners[event_type][entity_id]
            else:
                # Remove entire event_type
                for ent_id in self.event_listeners[event_type].keys():
                    for lid in self.event_listeners[event_type][ent_id].keys():
                        self.remove_event_listener(event_type, ent_id, lid)

    def add_haonline_listener(self, target: Callable[[], None]) -> None:
        """Add HA Online listener."""
        self.haonline_listeners.append(target)

    def signal_ha_online(self) -> None:
        """Call events if HA goes online."""
        for target in self.haonline_listeners:
            target()

    def remove_every_second_listener(self, name: str) -> None:
        """Remove regular listener."""
        if name in self.every_second_listeners:
            del self.every_second_listeners[name]
