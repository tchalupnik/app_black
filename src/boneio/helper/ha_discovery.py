"""Home Assistant discovery message generation using Pydantic models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from boneio.const import (
    CLOSE,
    CLOSED,
    CLOSING,
    COVER,
    DOUBLE,
    INPUT,
    INPUT_SENSOR,
    LONG,
    NUMERIC,
    OFF,
    ON,
    OPEN,
    OPENING,
    RELAY,
    SELECT,
    SENSOR,
    SINGLE,
    STATE,
    STOP,
)
from boneio.version import __version__


def ha_sensor_availabilty_message(
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
) -> dict[str, Any]:
    """Create SENSOR availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    sensor_message = HaSensorMessage(
        availability=availability,
        device=device_info,
        name=name or f"Sensor {id}",
        state_topic=f"{topic}/{SENSOR}/{id}",
        unique_id=f"{topic}{SENSOR}{id}",
        unit_of_measurement=unit_of_measurement,
        device_class=device_class,
        state_class=state_class,
    )

    result = sensor_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


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


class HaDiscoveryMessage(BaseModel):
    """Base Home Assistant discovery message."""

    availability: list[HaAvailabilityTopic]
    device: HaDeviceInfo
    name: str
    state_topic: str
    unique_id: str
    optimistic: bool = False

    # Optional fields that many entities use
    device_class: str | None = None
    unit_of_measurement: str | None = None
    state_class: str | None = None
    icon: str | None = None
    value_template: str | None = None
    state_value_template: str | None = None


class HaLightMessage(HaDiscoveryMessage):
    """Home Assistant light discovery message."""

    command_topic: str
    payload_off: str = OFF
    payload_on: str = ON
    state_value_template: str = "{{ value_json.state }}"


class HaLedMessage(HaDiscoveryMessage):
    """Home Assistant LED (dimmable light) discovery message."""

    command_topic: str
    brightness_state_topic: str
    brightness_command_topic: str
    brightness_scale: int = 65535
    payload_off: str = OFF
    payload_on: str = ON
    state_value_template: str = "{{ value_json.state }}"
    brightness_value_template: str = "{{ value_json.brightness }}"


class HaButtonMessage(HaDiscoveryMessage):
    """Home Assistant button discovery message."""

    command_topic: str
    payload_press: str


class HaSwitchMessage(HaDiscoveryMessage):
    """Home Assistant switch discovery message."""

    command_topic: str
    payload_off: str = OFF
    payload_on: str = ON
    value_template: str = "{{ value_json.state }}"


class HaValveMessage(HaDiscoveryMessage):
    """Home Assistant valve discovery message."""

    command_topic: str
    payload_close: str = OFF
    payload_open: str = ON
    state_open: str = ON
    state_closed: str = OFF
    reports_position: bool = False
    value_template: str = "{{ value_json.state }}"


class HaEventMessage(HaDiscoveryMessage):
    """Home Assistant event discovery message."""

    icon: str = "mdi:gesture-double-tap"
    event_types: list[str] = [SINGLE, DOUBLE, LONG]


class HaSensorMessage(HaDiscoveryMessage):
    """Home Assistant sensor discovery message."""

    # Sensor-specific fields are handled via the base class optional fields


class HaBinarySensorMessage(HaDiscoveryMessage):
    """Home Assistant binary sensor discovery message."""

    payload_on: str = "pressed"
    payload_off: str = "released"


class HaCoverMessage(HaDiscoveryMessage):
    """Home Assistant cover discovery message."""

    command_topic: str
    set_position_topic: str | None = None
    position_topic: str | None = None
    position_template: str | None = None
    tilt_command_topic: str | None = None
    tilt_status_topic: str | None = None
    tilt_status_template: str | None = None
    payload_open: str = OPEN
    payload_close: str = CLOSE
    payload_stop: str = STOP
    payload_stop_tilt: str | None = None
    state_open: str = OPEN
    state_opening: str = OPENING
    state_closed: str = CLOSED
    state_closing: str = CLOSING


class HaModbusMessage(HaDiscoveryMessage):
    """Home Assistant modbus discovery message with different unique_id pattern."""


def ha_availabilty_message(
    id: str,
    name: str,
    topic: str = "boneIO",
    device_name: str = "boneIO",
    device_type: str = INPUT,
    model: str = "boneIO Relay Board",
    web_url: str | None = None,
    entity_category: str | None = None,
    device_class: str | None = None,
    unit_of_measurement: str | None = None,
    state_class: str | None = None,
    icon: str | None = None,
    value_template: str | None = None,
) -> dict[str, Any]:
    """Create availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
        configuration_url=web_url,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    message = HaDiscoveryMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/{device_type}/{id}",
        unique_id=f"{topic}{device_type}{id}",
        device_class=device_class,
        unit_of_measurement=unit_of_measurement,
        state_class=state_class,
        icon=icon,
        value_template=value_template,
    )

    result = message.model_dump(exclude_none=True)

    # Add entity_category if provided (not part of base discovery message)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def ha_virtual_energy_sensor_discovery_message(
    topic: str,
    relay_id: str,
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """
    Generate MQTT autodiscovery messages for Home Assistant for virtual power and energy sensors.
    Returns discovery message for energy sensor.
    """
    return ha_availabilty_message(
        id=relay_id,
        name=name or f"{relay_id} Energy",
        topic=topic,
        device_name=device_name,
        model=model,
        device_type=SENSOR,
        state_class="total_increasing",
        device_class="energy",
        unit_of_measurement="Wh",
        entity_category=entity_category,
    )


def ha_light_availabilty_message(
    id: str,
    topic: str = "boneIO",
    device_type: str = RELAY,
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create LIGHT availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    light_message = HaLightMessage(
        availability=availability,
        device=device_info,
        name=name or f"Light {id}",
        state_topic=f"{topic}/{device_type}/{id}",
        unique_id=f"{topic}{device_type}{id}",
        command_topic=f"{topic}/cmd/{device_type}/{id}/set",
    )

    result = light_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def ha_led_availabilty_message(
    id: str,
    topic: str = "boneIO",
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create LED availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    led_message = HaLedMessage(
        availability=availability,
        device=device_info,
        name=name or f"LED {id}",
        state_topic=f"{topic}/{RELAY}/{id}",
        unique_id=f"{topic}{RELAY}{id}",
        command_topic=f"{topic}/cmd/{RELAY}/{id}/set",
        brightness_state_topic=f"{topic}/{RELAY}/{id}",
        brightness_command_topic=f"{topic}/cmd/{RELAY}/{id}/set_brightness",
    )

    result = led_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def ha_button_availabilty_message(
    id: str,
    topic: str = "boneIO",
    payload_press: str = "reload",
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create BUTTON availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    button_message = HaButtonMessage(
        availability=availability,
        device=device_info,
        name=name or f"Button {id}",
        state_topic=f"{topic}/button/{id}",
        unique_id=f"{topic}button{id}",
        command_topic=f"{topic}/cmd/button/{id}/set",
        payload_press=payload_press,
    )

    result = button_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def ha_switch_availabilty_message(
    id: str,
    topic: str = "boneIO",
    device_type: str = RELAY,
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create SWITCH availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    switch_message = HaSwitchMessage(
        availability=availability,
        device=device_info,
        name=name or f"Switch {id}",
        state_topic=f"{topic}/{device_type}/{id}",
        unique_id=f"{topic}{device_type}{id}",
        command_topic=f"{topic}/cmd/{device_type}/{id}/set",
    )

    result = switch_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def ha_valve_availabilty_message(
    id: str,
    topic: str = "boneIO",
    device_type: str = RELAY,
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create Valve availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    valve_message = HaValveMessage(
        availability=availability,
        device=device_info,
        name=name or f"Valve {id}",
        state_topic=f"{topic}/{device_type}/{id}",
        unique_id=f"{topic}{device_type}{id}",
        command_topic=f"{topic}/cmd/{device_type}/{id}/set",
    )

    result = valve_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def ha_event_availabilty_message(
    id: str,
    name: str,
    device_class: str,
    topic: str = "boneIO",
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create EVENT availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    event_message = HaEventMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/{INPUT}/{id}",
        unique_id=f"{topic}{INPUT}{id}",
        device_class=device_class,
    )

    result = event_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def ha_adc_sensor_availabilty_message(
    id: str,
    topic: str = "boneIO",
    name: str | None = None,
    device_name: str = "boneIO",
    model: str = "boneIO Relay Board",
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create ADC SENSOR availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    sensor_message = HaSensorMessage(
        availability=availability,
        device=device_info,
        name=name or f"ADC {id}",
        state_topic=f"{topic}/{SENSOR}/{id}",
        unique_id=f"{topic}{SENSOR}{id}",
        unit_of_measurement="V",
        device_class="voltage",
        state_class="measurement",
    )

    result = sensor_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def ha_binary_sensor_availabilty_message(
    id: str,
    name: str,
    device_class: str,
    topic: str = "boneIO",
    model: str = "boneIO Relay Board",
    device_name: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name or f"boneIO {topic}",
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    binary_sensor_message = HaBinarySensorMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/{INPUT_SENSOR}/{id}",
        unique_id=f"{topic}{INPUT_SENSOR}{id}",
        device_class=device_class,
        payload_on="pressed",
        payload_off="released",
    )

    result = binary_sensor_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def ha_sensor_ina_availabilty_message(
    id: str,
    name: str,
    topic: str = "boneIO",
    model: str = "boneIO Relay Board",
    device_name: str | None = None,
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name or f"boneIO {topic}",
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    sensor_message = HaSensorMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/{SENSOR}/{id}",
        unique_id=f"{topic}{SENSOR}{id}",
        state_class="measurement",
        value_template="{{ value_json.state }}",
        unit_of_measurement=unit_of_measurement,
        device_class=device_class,
    )

    result = sensor_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def ha_sensor_temp_availabilty_message(
    id: str,
    name: str,
    topic: str = "boneIO",
    model: str = "boneIO Relay Board",
    device_name: str | None = None,
    unit_of_measurement: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name or f"boneIO {topic}",
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    sensor_message = HaSensorMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/{SENSOR}/{id}",
        unique_id=f"{topic}{SENSOR}{id}",
        device_class="temperature",
        state_class="measurement",
        value_template="{{ value_json.state }}",
        unit_of_measurement=unit_of_measurement,
    )

    result = sensor_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def modbus_availabilty_message(
    id: str,
    entity_id: str,
    name: str,
    state_topic_base: str,
    topic: str,
    model: str,
    device_type: str = SENSOR,
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    state_class: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create Modbus availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[id],
        model=model,
        name=name,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{id}/{STATE}")]

    modbus_message = HaModbusMessage(
        availability=availability,
        device=device_info,
        name=entity_id,
        state_topic=f"{topic}/{device_type}/{id}/{state_topic_base}",
        unique_id=f"{topic}{entity_id.replace('_', '').lower()}{name.lower()}",
        unit_of_measurement=unit_of_measurement,
        device_class=device_class,
        state_class=state_class,
    )

    result = modbus_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def modbus_sensor_availabilty_message(
    id: str,
    sensor_id: str,
    name: str,
    state_topic_base: str,
    topic: str,
    model: str,
    device_type: str = SENSOR,
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    state_class: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create Modbus Sensor availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[id],
        model=model,
        name=name,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{id}/{STATE}")]

    modbus_message = HaModbusMessage(
        availability=availability,
        device=device_info,
        name=sensor_id,
        state_topic=f"{topic}/{device_type}/{id}/{state_topic_base}",
        unique_id=f"{topic}{sensor_id.replace('_', '').lower()}{name.lower()}",
        unit_of_measurement=unit_of_measurement,
        device_class=device_class,
        state_class=state_class,
    )

    result = modbus_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def modbus_select_availabilty_message(
    id: str,
    entity_id: str,
    name: str,
    state_topic_base: str,
    topic: str,
    model: str,
    device_type: str = SELECT,
    options: list[str] | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create Modbus Select availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[id],
        model=model,
        name=name,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{id}/{STATE}")]

    modbus_message = HaModbusMessage(
        availability=availability,
        device=device_info,
        name=entity_id,
        state_topic=f"{topic}/{device_type}/{id}/{state_topic_base}",
        unique_id=f"{topic}{entity_id.replace('_', '').lower()}{name.lower()}",
    )

    result = modbus_message.model_dump(exclude_none=True)
    if options:
        result["options"] = options
    if entity_category:
        result["entity_category"] = entity_category

    return result


def modbus_numeric_availabilty_message(
    id: str,
    entity_id: str,
    name: str,
    state_topic_base: str,
    topic: str,
    model: str,
    device_type: str = NUMERIC,
    min: float | None = None,
    max: float | None = None,
    step: float | None = None,
    unit_of_measurement: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create Modbus Numeric availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[id],
        model=model,
        name=name,
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{id}/{STATE}")]

    modbus_message = HaModbusMessage(
        availability=availability,
        device=device_info,
        name=entity_id,
        state_topic=f"{topic}/{device_type}/{id}/{state_topic_base}",
        unique_id=f"{topic}{entity_id.replace('_', '').lower()}{name.lower()}",
        unit_of_measurement=unit_of_measurement,
    )

    result = modbus_message.model_dump(exclude_none=True)
    if min is not None:
        result["min"] = min
    if max is not None:
        result["max"] = max
    if step is not None:
        result["step"] = step
    if entity_category:
        result["entity_category"] = entity_category

    return result


def ha_cover_availabilty_message(
    id: str,
    name: str,
    device_class: str,
    topic: str = "boneIO",
    model: str = "boneIO Relay Board",
    device_name: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create Cover availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name or f"boneIO {topic}",
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    cover_message = HaCoverMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/{COVER}/{id}/state",
        unique_id=f"{topic}{COVER}{id}",
        device_class=device_class,
        command_topic=f"{topic}/cmd/cover/{id}/set",
        set_position_topic=f"{topic}/cmd/cover/{id}/pos",
        payload_open=OPEN,
        payload_close=CLOSE,
        payload_stop=STOP,
        state_open=OPEN,
        state_opening=OPENING,
        state_closed=CLOSED,
        state_closing=CLOSING,
        position_template="{{ value_json.position }}",
        position_topic=f"{topic}/{COVER}/{id}/pos",
    )

    result = cover_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result


def ha_cover_with_tilt_availabilty_message(
    id: str,
    name: str,
    device_class: str,
    topic: str = "boneIO",
    model: str = "boneIO Relay Board",
    device_name: str | None = None,
    entity_category: str | None = None,
    web_url: str | None = None,
) -> dict[str, Any]:
    """Create Cover with tilt availability topic for HA."""
    device_info = HaDeviceInfo(
        identifiers=[topic],
        model=model,
        name=device_name or f"boneIO {topic}",
    )

    availability = [HaAvailabilityTopic(topic=f"{topic}/{STATE}")]

    cover_message = HaCoverMessage(
        availability=availability,
        device=device_info,
        name=name,
        state_topic=f"{topic}/{COVER}/{id}/state",
        unique_id=f"{topic}{COVER}{id}",
        device_class=device_class,
        command_topic=f"{topic}/cmd/cover/{id}/set",
        set_position_topic=f"{topic}/cmd/cover/{id}/pos",
        tilt_command_topic=f"{topic}/cmd/cover/{id}/tilt",
        payload_open=OPEN,
        payload_close=CLOSE,
        payload_stop=STOP,
        payload_stop_tilt=STOP,
        state_open=OPEN,
        state_opening=OPENING,
        state_closed=CLOSED,
        state_closing=CLOSING,
        position_topic=f"{topic}/{COVER}/{id}/pos",
        tilt_status_topic=f"{topic}/{COVER}/{id}/pos",
        position_template="{{ value_json.position }}",
        tilt_status_template="{{ value_json.tilt }}",
    )

    result = cover_message.model_dump(exclude_none=True)
    if entity_category:
        result["entity_category"] = entity_category

    return result
