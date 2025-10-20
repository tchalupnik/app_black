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


class HaMqttBinarySensor(BaseModel):
    platform: str = "binary_sensor"
    state_topic: str


class HaMqttSensor(BaseModel):
    platform: str = "sensor"
    state_topic: str


class HaMqttButton(BaseModel):
    platform: str = "button"
    command_topic: str


class HaMqttNumber(BaseModel):
    platform: str = "number"
    command_topic: str


class HaMqttSelect(BaseModel):
    platform: str = "select"
    command_topic: str
    options: list[str]


class HaMqttSwitch(BaseModel):
    platform: str = "switch"
    command_topic: str


class HaMqttLight(BaseModel):
    platform: str = "light"
    command_topic: str


class HaMqttValve(BaseModel):
    platform: str = "valve"


class HaMqttCover(BaseModel):
    platform: str = "cover"


class HaMqttEvent(BaseModel):
    platform: str = "event"
    state_topic: str
    event_types: list[str]


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

    # Number entity configuration
    min: float | None = None
    max: float | None = None
    step: float | None = None
    mode: str | None = None  # \"auto\", \"slider\", \"box\"

    # Enhanced modbus-specific fields
    retain: bool = False


def ha_sensor_availability_message(
    id: str,
    topic: str = "boneIO",
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    state_class: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
    value_template: str | None = None,
    icon: str | None = None,
) -> HaSensorMessage:
    """Create SENSOR availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaSensorMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/sensor/{id}",
        unique_id=f"{topic}sensor{id}",
        unit_of_measurement=unit_of_measurement,
        device_class=device_class,
        state_class=state_class,
        entity_category=entity_category,
        value_template=value_template,
        icon=icon,
    )


def ha_virtual_energy_sensor_discovery_message(
    topic: str,
    relay_id: str,
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaDiscoveryMessage:
    """
    Generate MQTT autodiscovery messages for Home Assistant for virtual power and energy sensors.
    Returns discovery message for energy sensor.
    """
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaDiscoveryMessage(
        availability=availability,
        device=device_info,
        name=name or f"{relay_id} Energy",
        state_topic=f"{topic}/sensor/{relay_id}",
        unique_id=f"{topic}sensor{relay_id}",
        device_class="energy",
        unit_of_measurement="Wh",
        state_class="total_increasing",
        entity_category=entity_category,
    )


def ha_light_availability_message(
    id: str,
    topic: str = "boneIO",
    device_type: str = "relay",
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaLightMessage:
    """Create LIGHT availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaLightMessage(
        availability=availability,
        device=device_info,
        name=name or f"Light {id}",
        state_topic=f"{topic}/{device_type}/{id}",
        unique_id=f"{topic}{device_type}{id}",
        command_topic=f"{topic}/cmd/{device_type}/{id}/set",
        entity_category=entity_category,
    )


def ha_led_availability_message(
    id: str,
    topic: str = "boneIO",
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaLedMessage:
    """Create LED availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaLedMessage(
        availability=availability,
        device=device_info,
        name=name or f"LED {id}",
        state_topic=f"{topic}/relay/{id}",
        unique_id=f"{topic}relay{id}",
        command_topic=f"{topic}/cmd/relay/{id}/set",
        brightness_state_topic=f"{topic}/relay/{id}",
        brightness_command_topic=f"{topic}/cmd/relay/{id}/set_brightness",
        entity_category=entity_category,
    )


def ha_button_availability_message(
    id: str,
    topic: str = "boneIO",
    payload_press: str = "reload",
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaButtonMessage:
    """Create BUTTON availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaButtonMessage(
        availability=availability,
        device=device_info,
        name=name or f"Button {id}",
        unique_id=f"{topic}button{id}",
        command_topic=f"{topic}/cmd/button/{id}/set",
        payload_press=payload_press,
        entity_category=entity_category,
    )


def ha_switch_availability_message(
    id: str,
    topic: str = "boneIO",
    device_type: str = "relay",
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaSwitchMessage:
    """Create SWITCH availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaSwitchMessage(
        availability=availability,
        device=device_info,
        name=name or f"Switch {id}",
        state_topic=f"{topic}/{device_type}/{id}",
        unique_id=f"{topic}{device_type}{id}",
        command_topic=f"{topic}/cmd/{device_type}/{id}/set",
        entity_category=entity_category,
    )


def ha_valve_availability_message(
    id: str,
    topic: str = "boneIO",
    device_type: str = "relay",
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaValveMessage:
    """Create Valve availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaValveMessage(
        availability=availability,
        device=device_info,
        name=name or f"Valve {id}",
        state_topic=f"{topic}/{device_type}/{id}",
        unique_id=f"{topic}{device_type}{id}",
        command_topic=f"{topic}/cmd/{device_type}/{id}/set",
        entity_category=entity_category,
    )


def ha_event_availability_message(
    id: str,
    name: str,
    device_class: str,
    topic: str = "boneIO",
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaEventMessage:
    """Create EVENT availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaEventMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/input/{id}",
        unique_id=f"{topic}input{id}",
        device_class=device_class,
        entity_category=entity_category,
    )


def ha_adc_sensor_availability_message(
    id: str,
    topic: str = "boneIO",
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaSensorMessage:
    """Create ADC SENSOR availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaSensorMessage(
        availability=availability,
        device=device_info,
        name=name or f"ADC {id}",
        state_topic=f"{topic}/sensor/{id}",
        unique_id=f"{topic}sensor{id}",
        unit_of_measurement="V",
        device_class="voltage",
        state_class="measurement",
        entity_category=entity_category,
    )


def ha_binary_sensor_availability_message(
    id: str,
    name: str,
    device_class: str,
    topic: str = "boneIO",
    model: str = "boneIO Relay Board",
    device_name: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaBinarySensorMessage:
    """Create availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name or f"boneIO {topic}",
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaBinarySensorMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/inputsensor/{id}",
        unique_id=f"{topic}inputsensor{id}",
        device_class=device_class,
        entity_category=entity_category,
    )


def ha_sensor_ina_availability_message(
    id: str,
    name: str,
    topic: str = "boneIO",
    model: str = "boneIO Relay Board",
    device_name: str | None = None,
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaSensorMessage:
    """Create availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name or f"boneIO {topic}",
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaSensorMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/sensor/{id}",
        unique_id=f"{topic}sensor{id}",
        state_class="measurement",
        value_template="{{ value_json.state }}",
        unit_of_measurement=unit_of_measurement,
        device_class=device_class,
        entity_category=entity_category,
    )


def ha_sensor_temp_availability_message(
    id: str,
    name: str,
    topic: str = "boneIO",
    model: str = "boneIO Relay Board",
    device_name: str | None = None,
    unit_of_measurement: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaSensorMessage:
    """Create availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name or f"boneIO {topic}",
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaSensorMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/sensor/{id}",
        unique_id=f"{topic}sensor{id}",
        device_class="temperature",
        state_class="measurement",
        value_template="{{ value_json.state }}",
        unit_of_measurement=unit_of_measurement,
        entity_category=entity_category,
    )


def modbus_availability_message(
    id: str,
    entity_id: str,
    name: str,
    state_topic_base: str,
    topic: str,
    model: str,
    device_type: str = "sensor",
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    state_class: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaModbusMessage:
    """Create Modbus availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[id],
        model=model,
        name=name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{id}/state")]

    return HaModbusMessage(
        availability=availability,
        device=device_info,
        name=entity_id,
        state_topic=f"{topic}/{device_type}/{id}/{state_topic_base}",
        unique_id=f"{topic}{entity_id.replace('_', '').lower()}{name.lower()}",
        unit_of_measurement=unit_of_measurement,
        device_class=device_class,
        state_class=state_class,
        entity_category=entity_category,
    )


def modbus_sensor_availability_message(
    id: str,
    sensor_id: str,
    name: str,
    state_topic_base: str,
    topic: str,
    model: str,
    device_type: str = "sensor",
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    state_class: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaModbusMessage:
    """Create Modbus Sensor availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[id],
        model=model,
        name=name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{id}/state")]

    return HaModbusMessage(
        availability=availability,
        device=device_info,
        name=sensor_id,
        state_topic=f"{topic}/{device_type}/{id}/{state_topic_base}",
        unique_id=f"{topic}{sensor_id.replace('_', '').lower()}{name.lower()}",
        unit_of_measurement=unit_of_measurement,
        device_class=device_class,
        state_class=state_class,
        entity_category=entity_category,
    )


def modbus_select_availability_message(
    id: str,
    entity_id: str,
    name: str,
    state_topic_base: str,
    topic: str,
    model: str,
    device_type: str = "select",
    options: list[str] | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaModbusMessage:
    """Create Modbus Select availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[id],
        model=model,
        name=name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{id}/state")]

    return HaModbusMessage(
        availability=availability,
        device=device_info,
        name=entity_id,
        state_topic=f"{topic}/{device_type}/{id}/{state_topic_base}",
        unique_id=f"{topic}{entity_id.replace('_', '').lower()}{name.lower()}",
        entity_category=entity_category,
        options=options,
    )


def modbus_numeric_availability_message(
    id: str,
    entity_id: str,
    name: str,
    state_topic_base: str,
    topic: str,
    model: str,
    device_type: str = "number",
    min: float | None = None,
    max: float | None = None,
    step: float | None = None,
    unit_of_measurement: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
    value_template: str | None = None,
) -> HaModbusMessage:
    """Create Modbus Numeric availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[id],
        model=model,
        name=name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{id}/state")]

    return HaModbusMessage(
        availability=availability,
        device=device_info,
        name=entity_id,
        state_topic=f"{topic}/{device_type}/{id}/{state_topic_base}",
        unique_id=f"{topic}{entity_id.replace('_', '').lower()}{name.lower()}",
        unit_of_measurement=unit_of_measurement,
        min=min,
        max=max,
        step=step,
        entity_category=entity_category,
        value_template=value_template,
    )


def ha_cover_availability_message(
    id: str,
    name: str,
    device_class: str,
    topic: str = "boneIO",
    model: str = "boneIO Relay Board",
    device_name: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
    value_template: str | None = None,
) -> HaCoverMessage:
    """Create Cover availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name or f"boneIO {topic}",
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaCoverMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/cover/{id}/state",
        unique_id=f"{topic}cover{id}",
        device_class=device_class,
        command_topic=f"{topic}/cmd/cover/{id}/set",
        set_position_topic=f"{topic}/cmd/cover/{id}/pos",
        position_template="{{ value_json.position }}",
        position_topic=f"{topic}/cover/{id}/pos",
        entity_category=entity_category,
        value_template=value_template,
    )


def ha_cover_with_tilt_availability_message(
    id: str,
    name: str,
    device_class: str,
    topic: str = "boneIO",
    model: str = "boneIO Relay Board",
    device_name: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> HaCoverMessage:
    """Create Cover with tilt availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name or f"boneIO {topic}",
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/state")]

    return HaCoverMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/cover/{id}/state",
        unique_id=f"{topic}cover{id}",
        device_class=device_class,
        command_topic=f"{topic}/cmd/cover/{id}/set",
        set_position_topic=f"{topic}/cmd/cover/{id}/pos",
        tilt_command_topic=f"{topic}/cmd/cover/{id}/tilt",
        payload_stop_tilt="stop",
        position_topic=f"{topic}/cover/{id}/pos",
        tilt_status_topic=f"{topic}/cover/{id}/tilt",
        position_template="{{ value_json.position }}",
        tilt_status_template="{{ value_json.tilt }}",
        entity_category=entity_category,
    )
