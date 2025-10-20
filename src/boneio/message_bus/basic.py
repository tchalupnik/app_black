"""Message bus abstraction for BoneIO."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeAlias

from pydantic import BaseModel, Field, RootModel

if TYPE_CHECKING:
    from boneio.helper.ha_discovery import HaDiscoveryMessage


class MqttAutoDiscoveryMessageType(str, Enum):
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


class MqttAutoDiscoveryMessage(BaseModel):
    type: MqttAutoDiscoveryMessageType
    topic: str
    payload: HaDiscoveryMessage


class MqttMessageBase(ABC, BaseModel):
    type_: str
    device_id: str
    command: str
    message: str


class RelaySetMqttMessage(MqttMessageBase):
    type_: Literal["relay"] = "relay"
    command: Literal["set"] = "set"
    message: Literal["ON", "OFF", "TOGGLE"]


class RelaySetBrightnessMqttMessage(MqttMessageBase):
    type_: Literal["relay"] = "relay"
    command: Literal["set_brightness"] = "set_brightness"
    message: int


_RelayMqttMessage: TypeAlias = RelaySetMqttMessage | RelaySetBrightnessMqttMessage


class RelayMqttMessage(RootModel[_RelayMqttMessage]):
    root: _RelayMqttMessage = Field(discriminator="command")


class CoverSetMqttMessage(MqttMessageBase):
    type_: Literal["cover"] = "cover"
    command: Literal["set"] = "set"
    message: Literal["open", "close", "stop", "toggle", "toggle_open", "toggle_close"]


class CoverPosMqttMessage(MqttMessageBase):
    type_: Literal["cover"] = "cover"
    command: Literal["pos"] = "pos"
    message: int


class CoverTiltMqttMessage(MqttMessageBase):
    type_: Literal["cover"] = "cover"
    command: Literal["tilt"] = "tilt"
    message: int | Literal["stop"]


_CoverMqttMessage: TypeAlias = (
    CoverSetMqttMessage | CoverPosMqttMessage | CoverTiltMqttMessage
)


class CoverMqttMessage(RootModel[_CoverMqttMessage]):
    root: _CoverMqttMessage = Field(discriminator="command")


class GroupMqttMessage(MqttMessageBase):
    type_: Literal["group"] = "group"
    command: Literal["set"] = "set"
    message: Literal["ON", "OFF", "TOGGLE"]


class ButtonMqttMessage(MqttMessageBase):
    type_: Literal["button"] = "button"
    command: Literal["set"] = "set"
    message: Literal["reload", "restart", "inputs_reload", "cover_reload"]


class ModbusMqttMessageValue(BaseModel):
    device: str
    value: int | float | str


class ModbusMqttMessage(MqttMessageBase):
    type_: Literal["modbus"] = "modbus"
    command: Literal["set"] = "set"
    message: ModbusMqttMessageValue


_MqqtMessage: TypeAlias = (
    RelayMqttMessage
    | CoverMqttMessage
    | GroupMqttMessage
    | ButtonMqttMessage
    | ModbusMqttMessage
)


class MqttMessage(RootModel[_MqqtMessage]):
    root: _MqqtMessage = Field(discriminator="type_")


class ReceiveMessage(Protocol):
    async def __call__(self, topic: str, message: str) -> None: ...


class MessageBus(ABC):
    """Base class for message handling."""

    @abstractmethod
    def send_message(
        self, topic: str, payload: str | dict, retain: bool = False
    ) -> None:
        """Send a message."""

    @abstractmethod
    def is_connection_established(self) -> bool:
        """Get bus state."""

    @abstractmethod
    async def announce_offline(self) -> None:
        """Announce that the device is offline."""

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
    def add_autodiscovery_message(self, message: MqttAutoDiscoveryMessage) -> None:
        """Add an autodiscovery message."""

    @abstractmethod
    def clear_autodiscovery_messages_by_type(
        self, type: MqttAutoDiscoveryMessageType
    ) -> None:
        """Clean autodiscovery messages."""
