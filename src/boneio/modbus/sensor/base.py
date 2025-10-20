from __future__ import annotations

import logging
import time
from abc import ABC
from dataclasses import dataclass, field

from boneio.config import Config
from boneio.helper.filter import Filter
from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_sensor_availability_message,
)
from boneio.message_bus.basic import (
    MessageBus,
    MqttAutoDiscoveryMessage,
    MqttAutoDiscoveryMessageType,
)
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
    config: Config
    value_type: ValueType
    user_filters: Filter = field(default_factory=lambda: Filter())
    filter: Filter = field(default_factory=lambda: Filter())
    unit_of_measurement: str | None = None
    state_class: str | None = None
    device_class: str | None = None
    return_type: str | None = None
    ha_filter: str = "round(2)"
    last_timestamp: float = field(default_factory=time.time)
    write_address: int | None = None
    state: int | float | str | None = field(init=False, default=None)

    _ha_type_: MqttAutoDiscoveryMessageType = MqttAutoDiscoveryMessageType.SENSOR

    def __post_init__(self) -> None:
        self.decoded_name = self.name.replace(" ", "").lower()
        self._topic = (
            f"{self.config.get_ha_autodiscovery_topic_prefix()}/{self._ha_type_.value.lower()}/{self.config.get_topic_prefix()}{self.parent_id}"
            f"/{self.parent_id}{self.decoded_name.replace('_', '')}/config"
        )

    def set_state(self, value: int | float | str | None, timestamp: float) -> None:
        if isinstance(value, (int, float)):
            value = self.filter.apply_filters(value=value)
            value = self.user_filters.apply_filters(value=value)
        self.state = value
        self.last_timestamp = timestamp

    @property
    def id(self) -> str:
        return f"{self.parent_id}{self.decoded_name}"

    def send_ha_discovery(self) -> None:
        payload = self.discovery_message()
        _LOGGER.debug(
            "Sending %s discovery message for %s of %s",
            self._ha_type_,
            self.name,
            self.parent_id,
        )
        if self.config.mqtt is not None:
            self.message_bus.add_autodiscovery_message(
                message=MqttAutoDiscoveryMessage(
                    type=self._ha_type_, payload=payload, topic=self._topic
                )
            )

    def discovery_message(self) -> HaModbusMessage:
        return modbus_sensor_availability_message(
            topic=self.config.get_topic_prefix(),
            id=self.parent_id,
            name=self.parent_name,
            state_topic_base=str(self.base_address),
            model=self.parent_model,
            device_class=self.device_class,
            unit_of_measurement=self.unit_of_measurement,
            state_class=self.state_class,
            value_template=(
                f"{{{{ value_json.{self.decoded_name} | {self.ha_filter} }}}}"
                if self.ha_filter
                else f"{{{{ value_json.{self.decoded_name} }}}}"
            ),
            sensor_id=self.name,
        )

    def encode_value(self, value: int | float) -> int:
        raise NotImplementedError
