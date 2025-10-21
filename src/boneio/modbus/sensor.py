from __future__ import annotations

import logging
import time
from abc import ABC
from dataclasses import dataclass, field

from boneio.helper.filter import Filter
from boneio.helper.ha_discovery import (
    HaAvailabilityTopic,
    HaDeviceInfo,
    HaModbusMessage,
)
from boneio.message_bus.basic import AutoDiscoveryMessageType, MessageBus
from boneio.modbus.models import ValueType

_LOGGER = logging.getLogger(__name__)


@dataclass(kw_only=True)
class BaseSensor(ABC):
    name: str
    parent_id: str
    parent_name: str
    parent_model: str
    register_address: int
    base_address: int
    message_bus: MessageBus
    value_type: ValueType
    user_filters: Filter = field(default_factory=lambda: Filter())
    filter: Filter = field(default_factory=lambda: Filter())
    unit_of_measurement: str | None = None
    state_class: str | None = None
    device_class: str | None = None
    return_type: str | None = None
    ha_filter: str | None = None
    last_timestamp: float = field(default_factory=time.time)
    write_address: int | None = None
    state: int | float | str | None = field(init=False, default=None)

    _ha_type_: AutoDiscoveryMessageType = AutoDiscoveryMessageType.SENSOR

    def __post_init__(self) -> None:
        self.decoded_name = self.name.replace(" ", "").lower()

    def set_state(self, value: int | float | str | None, timestamp: float) -> None:
        if isinstance(value, (int, float)):
            value = self.filter.apply_filters(value=value)
            value = self.user_filters.apply_filters(value=value)
        self.state = value
        self.last_timestamp = timestamp

    @property
    def id(self) -> str:
        return f"{self.parent_id}{self.decoded_name}"

    def discovery_message(
        self,
        topic: str,
        device_info: HaDeviceInfo,
        availability: list[HaAvailabilityTopic],
    ) -> HaModbusMessage:
        return HaModbusMessage(
            availability=availability,
            device=device_info,
            name=self.name,
            state_topic=f"{topic}/sensor/{self.parent_id}/{str(self.base_address)}",
            unique_id=f"{topic}{self.name.replace('_', '').lower()}{self.name.lower()}",
            unit_of_measurement=self.unit_of_measurement,
            device_class=self.device_class,
            state_class=self.state_class,
            value_template=(
                f"{{{{ value_json.{self.decoded_name} | {self.ha_filter} }}}}"
                if self.ha_filter
                else f"{{{{ value_json.{self.decoded_name} }}}}"
            ),
        )

    def encode_value(self, value: str | float | int) -> int:
        raise NotImplementedError


@dataclass
class ModbusNumericSensor(BaseSensor):
    """"""


@dataclass
class ModbusBinarySensor(BaseSensor):
    _ha_type_: AutoDiscoveryMessageType = AutoDiscoveryMessageType.BINARY_SENSOR
    payload_off: str = "OFF"
    payload_on: str = "ON"

    def discovery_message(
        self,
        topic: str,
        device_info: HaDeviceInfo,
        availability: list[HaAvailabilityTopic],
    ) -> HaModbusMessage:
        return HaModbusMessage(
            availability=availability,
            device=device_info,
            name=self.name,
            state_topic=f"{topic}/sensor/{self.parent_id}/{str(self.base_address)}",
            unique_id=f"{topic}{self.name.replace('_', '').lower()}{self.parent_name.lower()}",
            unit_of_measurement=self.unit_of_measurement,
            device_class=self.device_class,
            payload_off=self.payload_off,
            payload_on=self.payload_on,
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
        )


@dataclass(kw_only=True)
class ModbusTextSensor(BaseSensor):
    value_mapping: dict[str, str]

    def set_state(self, value: int | float | str | None, timestamp: float) -> None:
        self.last_timestamp = timestamp
        if not isinstance(value, str):
            _LOGGER.warning(
                "ModbusTextSensor expected str value but got %s", type(value)
            )
            return
        self.state = self.value_mapping.get(str(value), "Unknown")
