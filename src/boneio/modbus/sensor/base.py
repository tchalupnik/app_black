from __future__ import annotations

import logging
import time

from boneio.config import Config, Filters, MqttAutodiscoveryMessage
from boneio.const import ID, MODEL, NAME, SENSOR
from boneio.helper.filter import Filter
from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_sensor_availabilty_message,
)
from boneio.message_bus.basic import MessageBus

_LOGGER = logging.getLogger(__name__)


class BaseSensor:
    _ha_type_ = SENSOR

    def __init__(
        self,
        name: str,
        parent: dict,
        message_bus: MessageBus,
        config: Config,
        unit_of_measurement: str | None = None,
        state_class: str | None = None,
        device_class: str | None = None,
        value_type: str | None = None,
        return_type: str | None = None,
        filters: list = None,
        user_filters: list[dict[Filters, float]] | None = None,
        ha_filter: str = "round(2)",
    ) -> None:
        if user_filters is None:
            user_filters = []
        if filters is None:
            filters = []
        self.name = name
        self._parent = parent
        self._decoded_name = self.name.replace(" ", "")
        self.decoded_name = self.name.replace(" ", "").lower()
        self.unit_of_measurement = unit_of_measurement
        self._state_class = state_class
        self._device_class = device_class
        self._message_bus = message_bus
        self.config = config
        self._user_filters = Filter(user_filters)
        self.filter = Filter(filters)
        self._value = None
        self.return_type = return_type
        self.value_type = value_type
        self._ha_filter = ha_filter
        self.last_timestamp = time.time()
        self._topic = (
            f"{self.config.get_ha_autodiscovery_topic_prefix()}/{self._ha_type_}/{self.config.get_topic_prefix()}{self._parent[ID]}"
            f"/{self._parent[ID]}{self.decoded_name.replace('_', '')}/config"
        )
        self.write_address: int | None = None

    def set_user_filters(self, user_filters: list[dict[Filters, float]]) -> None:
        self._user_filters = Filter(user_filters)

    def set_value(self, value: float | None, timestamp: float) -> None:
        if value is not None:
            value = self.filter.apply_filters(value=value)
            value = self._user_filters.apply_filters(value=value)
        self._value = value
        self.last_timestamp = timestamp

    def get_value(self) -> float | None:
        return self._value

    @property
    def state(self) -> str | float:
        """Give back state value."""
        return self._value

    @property
    def id(self) -> str:
        return f"{self._parent['id']}{self.decoded_name}"

    def send_ha_discovery(self):
        payload = self.discovery_message()
        _LOGGER.debug(
            "Sending %s discovery message for %s of %s",
            self._ha_type_,
            self.name,
            self._parent["id"],
        )
        self.config.mqtt.autodiscovery_messages.add_message(
            message=MqttAutodiscoveryMessage(
                payload=payload.model_dump(), topic=self._topic
            ),
            type=self._ha_type_,
        )
        self._message_bus.send_message(topic=self._topic, payload=payload)

    def discovery_message(self) -> HaModbusMessage:
        return modbus_sensor_availabilty_message(
            topic=self.config.get_topic_prefix(),
            id=self._parent[ID],
            name=self._parent[NAME],
            state_topic_base=str(self.base_address),
            model=self._parent[MODEL],
            device_class=self._device_class,
            unit_of_measurement=self.unit_of_measurement,
            state_class=self._state_class,
            value_template=(
                f"{{{{ value_json.{self.decoded_name} | {self._ha_filter} }}}}"
                if self._ha_filter
                else f"{{{{ value_json.{self.decoded_name} }}}}"
            ),
            sensor_id=self.name,
        )

    def encode_value(self, value: int | float) -> int:
        raise NotImplementedError


class ModbusBaseSensor(BaseSensor):
    def __init__(
        self,
        name: str,
        parent: dict,
        register_address: int,
        base_address: int,
        message_bus: MessageBus,
        config: Config,
        unit_of_measurement: str | None = None,
        state_class: str | None = None,
        device_class: str | None = None,
        value_type: str | None = None,
        return_type: str | None = None,
        filters: list | None = None,
        user_filters: list | None = None,
        ha_filter: str = "",
    ) -> None:
        """
        Initialize single sensor.
        :param name: name of sensor
        :param register_address: address of register
        :param base_address: address of base
        :param unit_of_measurement: unit of measurement
        :param state_class: state class
        :param device_class: device class
        :param value_type: type of value
        :param return_type: type of return
        :param user_filters: list of user filters
        :param filters: list of filters
        :param send_ha_autodiscovery: function for sending HA autodiscovery
        """
        super().__init__(
            name=name,
            parent=parent,
            unit_of_measurement=unit_of_measurement,
            state_class=state_class,
            device_class=device_class,
            value_type=value_type,
            return_type=return_type,
            filters=filters,
            message_bus=message_bus,
            config=config,
            user_filters=user_filters,
            ha_filter=ha_filter,
        )
        self.address = register_address
        self.base_address = base_address
