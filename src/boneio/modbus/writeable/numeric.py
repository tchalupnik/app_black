from __future__ import annotations

from dataclasses import dataclass

from boneio.helper.filter import Filter
from boneio.message_bus.basic import (
    AutoDiscoveryMessageType,
    HaAvailabilityTopic,
    HaDeviceInfo,
    HaModbusMessage,
)
from boneio.modbus.sensor import BaseSensor


@dataclass(kw_only=True)
class ModbusNumericWriteableEntityDiscrete(BaseSensor):
    write_address: int | None = None
    write_filters: Filter


@dataclass(kw_only=True)
class ModbusNumericWriteableEntity(ModbusNumericWriteableEntityDiscrete):
    _ha_type_: AutoDiscoveryMessageType = AutoDiscoveryMessageType.NUMBER

    def discovery_message(
        self,
        topic: str,
        device_info: HaDeviceInfo,
        availability: list[HaAvailabilityTopic],
    ) -> HaModbusMessage:
        return HaModbusMessage(
            availability=availability,
            device=device_info,
            name=self.name,
            state_topic=f"{topic}/sensor/{id}/{str(self.base_address)}",
            unique_id=f"{topic}{self.name.replace('_', '').lower()}{self.parent_name.lower()}",
            unit_of_measurement=self.unit_of_measurement,
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            command_topic=f"{topic}/cmd/modbus/{self.parent_id.lower()}/set",
            command_template='{"device": "'
            + self.decoded_name
            + '", "value": "{{ value }}"}',
        )

    def encode_value(self, value: str | float | int) -> int:
        try:
            value = float(value)
        except ValueError:
            return 0
        result = self.write_filters.apply_filters(value=value)
        if result is None:
            return 0
        return int(result)
