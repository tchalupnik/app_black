from __future__ import annotations

# Typing imports that create a circular dependency
from dataclasses import dataclass

from boneio.helper.filter import Filter
from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_numeric_availability_message,
)
from boneio.message_bus.basic import MqttAutoDiscoveryMessageType
from boneio.modbus.sensor.base import BaseSensor


@dataclass(kw_only=True)
class ModbusNumericWriteableEntityDiscrete(BaseSensor):
    write_address: int | None = None
    write_filters: Filter

    def discovery_message(self) -> HaModbusMessage:
        return modbus_numeric_availability_message(
            topic=self.config.get_topic_prefix(),
            id=self.parent_id,
            name=self.parent_name,
            state_topic_base=str(self.base_address),
            model=self.parent_model,
            device_type="sensor",  # because we send everything to boneio/sensor from modbus.
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            entity_id=self.name,
        )


class ModbusNumericWriteableEntity(ModbusNumericWriteableEntityDiscrete):
    _ha_type_: MqttAutoDiscoveryMessageType = MqttAutoDiscoveryMessageType.NUMBER

    def discovery_message(self) -> HaModbusMessage:
        return modbus_numeric_availability_message(
            topic=self.config.get_topic_prefix(),
            id=self.parent_id,
            name=self.parent_name,
            state_topic_base=str(self.base_address),
            model=self.parent_model,
            device_type="sensor",  # because we send everything to boneio/sensor from modbus.
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            entity_id=self.name,
            command_topic=f"{self.config.get_topic_prefix()}/cmd/modbus/{self.parent_id.lower()}/set",
            command_template='{"device": "'
            + self.decoded_name
            + '", "value": "{{ value }}"}',
        )

    def encode_value(self, value: float) -> int:
        value = self.write_filters.apply_filters(value=value)
        if value is None:
            return 0
        return int(value)
