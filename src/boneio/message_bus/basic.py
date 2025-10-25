"""Message bus abstraction for BoneIO."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from enum import Enum
from typing import Any, Literal, Protocol, TypeAlias

from pydantic import BaseModel, Field, RootModel

from boneio.config import EventActionTypes
from boneio.version import __version__


class HaAvailabilityTopic(BaseModel):
    """Home Assistant availability topic."""

    topic: str


class HaDeviceInfo(BaseModel):
    """Home Assistant device information."""

    identifiers: list[str]
    manufacturer: str = "boneIO"
    model: str
    name: str
    sw_version: str = __version__
    configuration_url: str | None = None


class HaBaseMessage(BaseModel):
    """Base Home Assistant MQTT discovery message."""

    # Core entity identification
    device: HaDeviceInfo
    name: str | None = None
    unique_id: str

    # Availability configuration
    availability: list[HaAvailabilityTopic] = Field(default_factory=list)
    availability_mode: str = "latest"  # "all", "any", "latest"

    # Common entity configuration
    device_class: str | None = None
    icon: str | None = None


class HaDiscoveryMessage(HaBaseMessage):
    """Home Assistant discovery message with state_topic (for most entities)."""

    state_topic: str | None = None

    # Value processing
    value_template: str | None = None
    force_update: bool = False


class HaLightMessage(HaDiscoveryMessage):
    """Home Assistant MQTT light discovery message."""

    command_topic: str
    payload_off: str = "OFF"
    payload_on: str = "ON"
    state_value_template: str = "{{ value_json.state }}"


class HaLedMessage(HaLightMessage):
    """Home Assistant LED (dimmable light) discovery message."""

    # Required brightness support for LEDs
    brightness_state_topic: str
    brightness_command_topic: str
    brightness_scale: int = 65535  # Higher precision for LEDs
    brightness_value_template: str = "{{ value_json.brightness }}"


class HaButtonMessage(HaDiscoveryMessage):
    """Home Assistant button discovery message."""

    command_topic: str
    payload_press: str
    entity_category: str


class HaSwitchMessage(HaDiscoveryMessage):
    """Home Assistant MQTT switch discovery message."""

    command_topic: str
    payload_off: str = "OFF"
    payload_on: str = "ON"
    retain: bool = False


class HaValveMessage(HaDiscoveryMessage):
    """Home Assistant MQTT valve discovery message."""

    command_topic: str
    payload_close: str = "OFF"
    payload_open: str = "ON"
    state_open: str = "ON"
    state_closed: str = "OFF"
    reports_position: bool = False
    value_template: str = "{{ value_json.state }}"


class HaEventMessage(HaDiscoveryMessage):
    """Home Assistant MQTT event discovery message."""

    event_types: list[EventActionTypes] = ["single", "double", "long"]
    icon: str = "mdi:gesture-double-tap"


class HaSensorMessage(HaDiscoveryMessage):
    """Home Assistant MQTT sensor discovery message.

    Inherits all needed fields from HaDiscoveryMessage.
    """

    unit_of_measurement: str | None = None
    # `measurement` `measurement_angle` `total` `total_increasing``
    state_class: str | None = None

    # Optional entity category (e.g., "diagnostic", "config")
    entity_category: str | None = None


class HaBinarySensorMessage(HaDiscoveryMessage):
    """Home Assistant MQTT binary sensor discovery message."""

    payload_on: str = "ON"
    payload_off: str = "OFF"


class HaCoverMessage(HaDiscoveryMessage):
    """Home Assistant MQTT cover discovery message."""

    command_topic: str

    # Optional position and tilt support
    position_topic: str | None = None
    set_position_topic: str | None = None
    position_template: str | None = None
    tilt_command_topic: str | None = None
    tilt_status_topic: str | None = None
    tilt_status_template: str | None = None


class HaModbusMessage(HaDiscoveryMessage):
    """Home Assistant modbus discovery message with different unique_id."""

    # Command topic for writable entities (number, select, etc.)
    command_topic: str | None = None
    command_template: str | None = None
    payload_off: str | None = None
    payload_on: str | None = None


class HaSelectMessage(HaModbusMessage):
    """Home Assistant MQTT select discovery message."""

    command_topic: str
    options: list[str] = Field(default_factory=list)


class AutoDiscoveryMessageType(str, Enum):
    """Enum for Auto Discovery Message Types."""

    SWITCH = "SWITCH"
    LIGHT = "LIGHT"
    BINARY_SENSOR = "BINARY_SENSOR"
    SENSOR = "SENSOR"
    COVER = "COVER"
    BUTTON = "BUTTON"
    EVENT = "EVENT"
    VALVE = "VALVE"
    TEXT_SENSOR = "TEXT_SENSOR"
    SELECT = "SELECT"
    NUMERIC = "NUMERIC"
    NUMBER = "NUMBER"


class AutoDiscoveryMessage(BaseModel):
    type: AutoDiscoveryMessageType
    topic: str
    payload: HaDiscoveryMessage


class MessageBase(ABC, BaseModel):
    type_: str
    device_id: str
    command: str
    message: str | int | ModbusMessageValue | CoverSetMessageState


class RelaySetMessage(MessageBase):
    type_: Literal["relay"] = "relay"
    command: Literal["set"] = "set"
    message: Literal["ON", "OFF", "TOGGLE"]


class RelaySetBrightnessMessage(MessageBase):
    type_: Literal["relay"] = "relay"
    command: Literal["set_brightness"] = "set_brightness"
    message: int


_RelayMessage: TypeAlias = RelaySetMessage | RelaySetBrightnessMessage


class RelayMessage(RootModel[_RelayMessage]):
    root: _RelayMessage = Field(discriminator="command")


class CoverSetMessageState(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    STOP = "STOP"
    TOGGLE = "TOGGLE"
    TOGGLE_OPEN = "TOGGLE_OPEN"
    TOGGLE_CLOSE = "TOGGLE_CLOSE"


class CoverSetMessage(MessageBase):
    type_: Literal["cover"] = "cover"
    command: Literal["set"] = "set"
    message: CoverSetMessageState


class CoverPosMessage(MessageBase):
    type_: Literal["cover"] = "cover"
    command: Literal["pos"] = "pos"
    message: int


class CoverTiltMessage(MessageBase):
    type_: Literal["cover"] = "cover"
    command: Literal["tilt"] = "tilt"
    message: int | Literal["stop"]


_CoverMessage: TypeAlias = CoverSetMessage | CoverPosMessage | CoverTiltMessage


class CoverMessage(RootModel[_CoverMessage]):
    root: _CoverMessage = Field(discriminator="command")


class GroupMessage(MessageBase):
    type_: Literal["group"] = "group"
    command: Literal["set"] = "set"
    message: Literal["ON", "OFF", "TOGGLE"]


class ButtonMessage(MessageBase):
    type_: Literal["button"] = "button"
    command: Literal["set"] = "set"
    message: Literal["reload", "restart", "inputs_reload", "cover_reload"]


class ModbusMessageValue(BaseModel):
    device: str
    value: int | float | str


class ModbusMessage(MessageBase):
    type_: Literal["modbus"] = "modbus"
    command: Literal["set"] = "set"
    message: ModbusMessageValue


_Message: TypeAlias = (
    RelayMessage | CoverMessage | GroupMessage | ButtonMessage | ModbusMessage
)


class Message(RootModel[_Message]):
    root: _Message = Field(discriminator="type_")


class ReceiveMessage(Protocol):
    async def __call__(self, topic: str, message: str) -> None: ...


class MessageBus(ABC):
    """Base class for payload handling."""

    @abstractmethod
    def send_message(
        self, topic: str, payload: str | None, retain: bool = False
    ) -> None:
        """Send a message."""

    @abstractmethod
    def is_connection_established(self) -> bool:
        """Get bus state."""

    @abstractmethod
    async def subscribe_and_listen(
        self, topic: str, callback: Callable[[str], Coroutine[Any, Any, None]]
    ) -> None:
        """Subscribe to a topic and listen for messages."""

    @abstractmethod
    async def unsubscribe_and_stop_listen(self, topic: str) -> None:
        """Unsubscribe from a topic and stop listening."""

    @abstractmethod
    async def subscribe(self, receive_message: ReceiveMessage) -> None:
        """Subscribe to a topic."""

    @abstractmethod
    def add_autodiscovery_message(self, message: AutoDiscoveryMessage) -> None:
        """Add an autodiscovery message."""

    @abstractmethod
    def clear_autodiscovery_messages_by_type(
        self, type: AutoDiscoveryMessageType
    ) -> None:
        """Clean autodiscovery messages."""
