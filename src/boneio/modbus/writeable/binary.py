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
class ModbusBinaryWriteableEntityDiscrete(BaseSensor):
    _ha_type_: AutoDiscoveryMessageType = AutoDiscoveryMessageType.BINARY_SENSOR

    write_address: int | None = None
    payload_off: str = "OFF"
    payload_on: str = "ON"
    write_filters: Filter | None = None

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
            state_topic=f"{topic}/sensor/{self.parent_id}/{str(self.base_address)}",
            unique_id=f"{topic}{self.name.replace('_', '').lower()}{self.parent_name.lower()}",
            unit_of_measurement=self.unit_of_measurement,
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            payload_off=self.payload_off,
            payload_on=self.payload_on,
        )
