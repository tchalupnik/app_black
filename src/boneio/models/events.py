"""Event models for the BoneIO system."""

from __future__ import annotations

from abc import ABC
from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, Discriminator

from boneio.models import (
    CoverState,
    HostSensorState,
    InputState,
    OutputState,
    SensorState,
)

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
