from __future__ import annotations

from dataclasses import dataclass

from boneio.message_bus.basic import (
    AutoDiscoveryMessageType,
    HaAvailabilityTopic,
    HaDeviceInfo,
    HaModbusMessage,
    HaSelectMessage,
)
from boneio.modbus.sensor import BaseSensor


@dataclass(kw_only=True)
class ModbusDerivedSelect(BaseSensor):
    decoded_name: str
    value_mapping: dict[str, str]
    _ha_type_: AutoDiscoveryMessageType = AutoDiscoveryMessageType.SELECT

    def discovery_message(
        self,
        topic: str,
        device_info: HaDeviceInfo,
        availability: list[HaAvailabilityTopic],
    ) -> HaModbusMessage:
        return HaSelectMessage(
            availability=availability,
            device=device_info,
            name=self.name,
            state_topic=f"{topic}/sensor/{self.parent_id}/{str(self.base_address)}",
            unique_id=f"{topic}{self.name.replace('_', '').lower()}{self.parent_name.lower()}",
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            options=[*self.value_mapping.values()],
            command_topic=f"{topic}/cmd/modbus/{self.parent_id.lower()}/set",
            command_template='{"device": "'
            + self.decoded_name
            + '", "value": "{{ value }}"}',
        )

    def evaluate_state(
        self, source_sensor_value: str | float | None, timestamp: float
    ) -> None:
        self._timestamp = timestamp
        self.state = self.value_mapping.get(str(source_sensor_value), "Unknown")

    def encode_value(self, value: str | float | int) -> int:
        for k, v in self.value_mapping.items():
            if v == value:
                return int(k)
        return 0
