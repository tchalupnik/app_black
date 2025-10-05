from __future__ import annotations

from dataclasses import dataclass

from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_sensor_availabilty_message,
)
from boneio.modbus.sensor.base import BaseSensor


@dataclass(kw_only=True)
class ModbusDerivedTextSensor(BaseSensor):
    decoded_name: str
    value_mapping: dict[str, str]
    _ha_type_: str = "text_sensor"
    state: str = ""

    def discovery_message(self) -> HaModbusMessage:
        return modbus_sensor_availabilty_message(
            topic=self.config.get_topic_prefix(),
            id=self.parent["id"],
            name=self.parent["name"],
            state_topic_base=str(self.base_address),
            model=self.parent["model"],
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            sensor_id=self.name,
        )

    def evaluate_state(
        self, source_sensor_value: int | float, timestamp: float
    ) -> None:
        self.timestamp = timestamp
        self.state = self.value_mapping.get(str(source_sensor_value), "Unknown")
