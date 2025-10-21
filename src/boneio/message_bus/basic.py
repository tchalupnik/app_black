"""Message bus abstraction for BoneIO."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeAlias

from pydantic import BaseModel, Field, RootModel

if TYPE_CHECKING:
    from boneio.helper.ha_discovery import HaDiscoveryMessage


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
    message: str | int | ModbusMessageValue


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


class CoverSetMessage(MessageBase):
    type_: Literal["cover"] = "cover"
    command: Literal["set"] = "set"
    message: Literal["open", "close", "stop", "toggle", "toggle_open", "toggle_close"]


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
    def add_autodiscovery_message(self, message: AutoDiscoveryMessage) -> None:
        """Add an autodiscovery message."""

    @abstractmethod
    def clear_autodiscovery_messages_by_type(
        self, type: AutoDiscoveryMessageType
    ) -> None:
        """Clean autodiscovery messages."""
