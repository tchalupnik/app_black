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
class ModbusBinaryWriteableEntityDiscrete(BaseSensor):
    _ha_type_: MqttAutoDiscoveryMessageType = MqttAutoDiscoveryMessageType.BINARY_SENSOR

    write_address: int | None = None
    payload_off: str = "OFF"
    payload_on: str = "ON"
    write_filters: Filter | None = None

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
            payload_off=self.payload_off,
            payload_on=self.payload_on,
        )
