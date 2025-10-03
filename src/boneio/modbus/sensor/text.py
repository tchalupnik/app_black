from __future__ import annotations

from dataclasses import dataclass

from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_sensor_availabilty_message,
)

from .base import BaseSensor


@dataclass(kw_only=True)
class ModbusTextSensor(BaseSensor):
    _ha_type_: str = "sensor"
    value_mapping: dict[str, str]

    @property
    def state(self) -> str:
        """Give rounded value of temperature."""
        return self.value or ""

    def set_value(self, value: str, timestamp: float) -> None:
        self.timestamp = timestamp
        self.value = self.value_mapping.get(str(value), "Unknown")

    def discovery_message(self) -> HaModbusMessage:
        return modbus_sensor_availabilty_message(
            topic=self.config.get_topic_prefix(),
            id=self.parent["id"],
            name=self.parent["name"],
            model=self.parent["model"],
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            sensor_id=self.name,
        )
