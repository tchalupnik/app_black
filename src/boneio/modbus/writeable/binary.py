from __future__ import annotations

# Typing imports that create a circular dependency
from dataclasses import dataclass

from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_numeric_availabilty_message,
)
from boneio.modbus.sensor.base import BaseSensor


@dataclass(kw_only=True)
class ModbusBinaryWriteableEntityDiscrete(BaseSensor):
    _ha_type_: str = "binary_sensor"
    write_address: int | None = None
    payload_off: str = "OFF"
    payload_on: str = "ON"
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
            payload_off=self.payload_off,
            payload_on=self.payload_on,
        )
