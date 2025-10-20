from __future__ import annotations

from dataclasses import dataclass

from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_sensor_availability_message,
)

from .base import BaseSensor


@dataclass(kw_only=True)
class ModbusTextSensor(BaseSensor):
    value_mapping: dict[str, str]

    def set_state(self, value: str, timestamp: float) -> None:
        self.last_timestamp = timestamp
        self.state = self.value_mapping.get(str(value), "Unknown")

    def discovery_message(self) -> HaModbusMessage:
        return modbus_sensor_availability_message(
            topic=self.config.get_topic_prefix(),
            id=self.parent_id,
            name=self.parent_name,
            model=self.parent_model,
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            sensor_id=self.name,
        )
