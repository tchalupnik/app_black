from __future__ import annotations
import logging
from typing import Callable, Union, Optional
from boneio.const import SENSOR, ID, MODEL, NAME
from boneio.helper.config import ConfigHelper
from boneio.helper.filter import Filter
from .utils import allowed_operations
from boneio.helper.ha_discovery import modbus_sensor_availabilty_message

_LOGGER = logging.getLogger(__name__)


class SingleSensor(Filter):

    def __init__(
        self,
        name: str,
        parent: dict,
        register_address: int,
        base_address: int,
        unit_of_measurement: str,
        state_class: str,
        device_class: str,
        value_type: str,
        return_type: str,
        filters: list,
        send_message: Callable[
            [str, Union[str, int, dict, None], Optional[bool]], None
        ],
        config_helper: ConfigHelper,
        user_filters: Optional[list] = [],
        ha_filter: str = "round(2)",
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
        self._name = name
        self._decoded_name = self._name.replace(" ", "")
        self._decoded_name_low = self._name.replace(" ", "").lower()
        self._register_address = register_address
        self._base_address = base_address
        self._unit_of_measurement = unit_of_measurement
        self._state_class = state_class
        self._device_class = device_class
        self._value_type = value_type
        self._user_filters = user_filters
        self._ha_filter = ha_filter
        self._filters = filters
        self._value = None
        self._return_type = return_type
        self._send_message = send_message
        self._config_helper = config_helper
        self._parent = parent
        self._topic = (
            f"{self._config_helper.ha_discovery_prefix}/{SENSOR}/{self._config_helper.topic_prefix}{self._parent[ID]}"
            f"/{self._parent[ID]}{self._decoded_name_low.replace('_', '')}/config"
        )

    def set_user_filters(self, user_filters: list) -> None:
        self._user_filters = user_filters

    def set_value(self, value):
        value = self._apply_filters(value=value)
        value = self._apply_filters(
            value=value,
            filters=self._user_filters,
        )
        self._value = value

    def send_ha_discovery(self):
        payload = self.discovery_message()
        _LOGGER.debug(
            "Sending discovery message for %s of %s",
            self._name,
            self._parent[ID],
        )
        self._config_helper.add_autodiscovery_msg(
            topic=self._topic, payload=payload, ha_type=SENSOR
        )
        self._send_message(topic=self._topic, payload=payload)

    def discovery_message(self):
        value_template = (
            f"{{{{ value_json.{self.decoded_name} | " f"{self._ha_filter} }}}}"
        )
        kwargs = {
            "unit_of_measurement": self._unit_of_measurement,
            "state_class": self._state_class,
            "value_template": value_template,
            "sensor_id": self._name,
        }
        if self._device_class:
            kwargs["device_class"] = self._device_class
        return modbus_sensor_availabilty_message(
            topic=self._config_helper.topic_prefix,
            id=self._parent[ID],
            name=self._parent[NAME],
            state_topic_base=str(self._base_address),
            model=self._parent[MODEL],
            **kwargs,
        )

    def get_value(self):
        return self._value

    @property
    def value_type(self) -> str:
        return self._value_type

    @property
    def return_type(self) -> str:
        return self._return_type

    @property
    def address(self) -> int:
        return self._register_address

    @property
    def base_address(self) -> int:
        return self._base_address

    @property
    def state(self) -> float:
        """Give rounded value of temperature."""
        return self._value or -1

    @property
    def decoded_name(self) -> str:
        return self._decoded_name_low

    @property
    def name(self) -> str:
        """Return name of the sensor."""
        return self._name

    @property
    def unit_of_measurement(self) -> str:
        return self._unit_of_measurement
