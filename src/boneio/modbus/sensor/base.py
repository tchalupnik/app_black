from __future__ import annotations

import logging
import time
from abc import ABC
from dataclasses import dataclass, field
from typing import Literal

from boneio.config import Config, MqttAutodiscoveryMessage
from boneio.helper.filter import Filter
from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_sensor_availabilty_message,
)
from boneio.message_bus.basic import MessageBus
from boneio.modbus.models import ValueType

_LOGGER = logging.getLogger(__name__)


@dataclass(kw_only=True)
class BaseSensor(ABC):
    name: str
    parent: dict[Literal["id", "name", "model"], str]
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

    _ha_type_: str = "sensor"

    def __post_init__(self) -> None:
        self.decoded_name = self.name.replace(" ", "").lower()
        self.value = None
        self._topic = (
            f"{self.config.get_ha_autodiscovery_topic_prefix()}/{self._ha_type_}/{self.config.get_topic_prefix()}{self.parent['id']}"
            f"/{self.parent['id']}{self.decoded_name.replace('_', '')}/config"
        )

    def set_value(self, value: float | None, timestamp: float) -> None:
        if value is not None:
            value = self.filter.apply_filters(value=value)
            value = self.user_filters.apply_filters(value=value)
        self.value = value
        self.last_timestamp = timestamp

    @property
    def state(self) -> float:
        """Give back state value."""
        return self.value

    @property
    def id(self) -> str:
        return f"{self.parent['id']}{self.decoded_name}"

    def send_ha_discovery(self):
        payload = self.discovery_message()
        _LOGGER.debug(
            "Sending %s discovery message for %s of %s",
            self._ha_type_,
            self.name,
            self.parent["id"],
        )
        self.config.mqtt.autodiscovery_messages.add_message(
            message=MqttAutodiscoveryMessage(
                payload=payload.model_dump(), topic=self._topic
            ),
            type=self._ha_type_,
        )
        self.message_bus.send_message(topic=self._topic, payload=payload)

    def discovery_message(self) -> HaModbusMessage:
        return modbus_sensor_availabilty_message(
            topic=self.config.get_topic_prefix(),
            id=self.parent["id"],
            name=self.parent["name"],
            state_topic_base=str(self.base_address),
            model=self.parent["model"],
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
