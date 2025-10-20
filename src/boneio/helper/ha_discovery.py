"""Home Assistant discovery message generation using Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field

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
    entity_category: str | None = None
    icon: str | None = None


class HaDiscoveryMessage(HaBaseMessage):
    """Home Assistant discovery message with state_topic (for most entities)."""

    state_topic: str | None = None

    # Value processing
    value_template: str | None = None
    force_update: bool = False

    # Sensor-specific fields
    unit_of_measurement: str | None = None
    state_class: str | None = None


class HaLightMessage(HaDiscoveryMessage):
    """Home Assistant MQTT light discovery message."""

    command_topic: str
    payload_off: str = "OFF"
    payload_on: str = "ON"
    retain: bool = False


class HaLedMessage(HaLightMessage):
    """Home Assistant LED (dimmable light) discovery message."""

    # Required brightness support for LEDs
    brightness_state_topic: str
    brightness_command_topic: str
    brightness_scale: int = 65535  # Higher precision for LEDs
    brightness_value_template: str | None = None


class HaButtonMessage(HaDiscoveryMessage):
    """Home Assistant button discovery message."""

    command_topic: str
    payload_press: str


class HaSwitchMessage(HaDiscoveryMessage):
    """Home Assistant MQTT switch discovery message."""

    command_topic: str
    payload_off: str = "OFF"
    payload_on: str = "ON"
    retain: bool = False


class HaValveMessage(HaDiscoveryMessage):
    """Home Assistant MQTT valve discovery message."""

    command_topic: str


class HaEventMessage(HaDiscoveryMessage):
    """Home Assistant MQTT event discovery message."""

    event_types: list[EventActionTypes] = ["single", "double", "long"]
    icon: str = "mdi:gesture-double-tap"


class HaSensorMessage(HaDiscoveryMessage):
    """Home Assistant MQTT sensor discovery message.

    Inherits all needed fields from HaDiscoveryMessage.
    """


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
