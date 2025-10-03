from __future__ import annotations

# Typing imports that create a circular dependency
from dataclasses import dataclass

from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_numeric_availabilty_message,
)
from boneio.modbus.sensor.base import BaseSensor


@dataclass(kw_only=True)
class ModbusNumericWriteableEntityDiscrete(BaseSensor):
    _ha_type_: str = "sensor"
    write_address: int | None = None
    write_filters: list | None = None

    def discovery_message(self) -> HaModbusMessage:
        return modbus_numeric_availabilty_message(
            topic=self.config.get_topic_prefix(),
            id=self.parent["id"],
            name=self.parent["name"],
            state_topic_base=str(self.base_address),
            model=self.parent["model"],
            device_type="sensor",  # because we send everything to boneio/sensor from modbus.
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            entity_id=self.name,
        )


class ModbusNumericWriteableEntity(ModbusNumericWriteableEntityDiscrete):
    _ha_type_: str = "number"

    def discovery_message(self) -> HaModbusMessage:
        return modbus_numeric_availabilty_message(
            topic=self.config.get_topic_prefix(),
            id=self.parent["id"],
            name=self.parent["name"],
            state_topic_base=str(self.base_address),
            model=self.parent["model"],
            device_type="sensor",  # because we send everything to boneio/sensor from modbus.
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            entity_id=self.name,
            mode="box",
            command_topic=f"{self.config.get_topic_prefix()}/cmd/modbus/{self.parent['id'].lower()}/set",
            command_template='{"device": "'
            + self.decoded_name
            + '", "value": "{{ value }}"}',
        )

    def encode_value(self, value: float) -> int:
        if self.write_filters:
            value = self.filter.apply_filters(value=value, filters=self.write_filters)
        return int(value)
