from __future__ import annotations

from dataclasses import dataclass

from boneio.message_bus.basic import AutoDiscoveryMessageType
from boneio.modbus.sensor import BaseSensor


@dataclass(kw_only=True)
class ModbusDerivedTextSensor(BaseSensor):
    decoded_name: str
    value_mapping: dict[str, str]
    _ha_type_: AutoDiscoveryMessageType = AutoDiscoveryMessageType.TEXT_SENSOR

    def evaluate_state(
        self, source_sensor_value: str | float | None, timestamp: float
    ) -> None:
        self.timestamp = timestamp
        self.state = self.value_mapping.get(str(source_sensor_value), "Unknown")
