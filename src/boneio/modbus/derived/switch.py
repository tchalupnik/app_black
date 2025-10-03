from __future__ import annotations

from dataclasses import dataclass

from boneio.config import ModbusDeviceData
from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_availabilty_message,
)
from boneio.modbus.sensor.base import BaseSensor


@dataclass(kw_only=True)
class ModbusDerivedSwitch(BaseSensor):
    context_config: ModbusDeviceData
    base_address: str
    decoded_name: str
    value_mapping: dict[str, str]
    payload_off: str = "OFF"
    payload_on: str = "ON"
    _ha_type_: str = "switch"

    @property
    def state(self) -> str:
        """Give rounded value of temperature."""
        return self.value or ""

    def discovery_message(self) -> HaModbusMessage:
        return modbus_availabilty_message(
            topic=self.config.get_topic_prefix(),
            id=self.parent["id"],
            name=self.parent["name"],
            state_topic_base=str(self.base_address),
            model=self.parent["model"],
            device_type="sensor",  # because we send everything to boneio/sensor from modbus.
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            entity_id=self.name,
            command_topic=f"{self.config.get_topic_prefix()}/cmd/modbus/{self.parent['id'].lower()}/set",
            command_template='{"device": "'
            + self.decoded_name
            + '", "value": "{{ value }}"}',
            payload_off=self.payload_off,
            payload_on=self.payload_on,
        )

    def evaluate_state(
        self, source_sensor_value: int | float, timestamp: float
    ) -> None:
        self.timestamp = timestamp
        self.value = self.value_mapping.get(str(source_sensor_value), "None")

    def encode_value(self, value: str | float | int) -> int:
        for k, v in self.value_mapping.items():
            if v == value:
                return int(k)
        return 0
