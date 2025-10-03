from __future__ import annotations

from dataclasses import dataclass

from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_numeric_availabilty_message,
)

from .base import BaseSensor


@dataclass
class ModbusBinarySensor(BaseSensor):
    _ha_type_: str = "binary_sensor"
    payload_off: str = "OFF"
    payload_on: str = "ON"

    def discovery_message(self) -> HaModbusMessage:
        msg = modbus_numeric_availabilty_message(
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
        return msg
