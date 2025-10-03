from __future__ import annotations

from dataclasses import dataclass

from boneio.config import ModbusDeviceData
from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_select_availabilty_message,
)
from boneio.modbus.sensor.base import BaseSensor


@dataclass(kw_only=True)
class ModbusDerivedSelect(BaseSensor):
    context_config: ModbusDeviceData
    source_sensor_base_address: str
    source_sensor_decoded_name: str
    value_mapping: dict[str, str]
    _ha_type_: str = "select"

    @property
    def state(self) -> str:
        """Give rounded value of temperature."""
        return self._value or ""

    def discovery_message(self) -> HaModbusMessage:
        return modbus_select_availabilty_message(
            topic=self.config.get_topic_prefix(),
            id=self.parent["id"],
            name=self.parent["name"],
            state_topic_base=str(self.source_sensor_base_address),
            model=self.parent["model"],
            device_type="sensor",  # because we send everything to boneio/sensor from modbus.
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            entity_id=self.name,
            options=[*self.value_mapping.values()],
            command_topic=f"{self.config.get_topic_prefix()}/cmd/modbus/{self.parent['id'].lower()}/set",
            command_template='{"device": "'
            + self.decoded_name
            + '", "value": "{{ value }}"}',
        )

    def evaluate_state(
        self, source_sensor_value: int | float, timestamp: float
    ) -> None:
        self._timestamp = timestamp
        self._value = self.value_mapping.get(str(source_sensor_value), "Unknown")

    def encode_value(self, value: str | float | int) -> int:
        for k, v in self.value_mapping.items():
            if v == value:
                return int(k)
        return 0
