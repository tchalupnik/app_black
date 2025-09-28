from __future__ import annotations

# Typing imports that create a circular dependency
from typing import TYPE_CHECKING

from boneio.config import Config
from boneio.const import ID, MODEL, NAME, NUMERIC, SENSOR
from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_numeric_availabilty_message,
)

if TYPE_CHECKING:
    from ..coordinator import ModbusCoordinator

from boneio.modbus.sensor.numeric import ModbusNumericSensor


class ModbusNumericWriteableEntityDiscrete(ModbusNumericSensor):
    _ha_type_ = SENSOR

    def __init__(
        self,
        coordinator: ModbusCoordinator,
        config: Config,
        write_address: int | None = None,
        write_filters: list | None = None,
        **kwargs,
    ):
        super().__init__(self, config=config, **kwargs)
        self._coordinator = coordinator
        self.write_address = write_address
        self._write_filters = write_filters

    def discovery_message(self) -> HaModbusMessage:
        return modbus_numeric_availabilty_message(
            topic=self.config.get_topic_prefix(),
            id=self._parent[ID],
            name=self._parent[NAME],
            state_topic_base=str(self.base_address),
            model=self._parent[MODEL],
            device_type=SENSOR,  # because we send everything to boneio/sensor from modbus.
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            entity_id=self.name,
        )


class ModbusNumericWriteableEntity(ModbusNumericWriteableEntityDiscrete):
    _ha_type_ = NUMERIC

    def discovery_message(self) -> HaModbusMessage:
        return modbus_numeric_availabilty_message(
            topic=self.config.get_topic_prefix(),
            id=self._parent[ID],
            name=self._parent[NAME],
            state_topic_base=str(self.base_address),
            model=self._parent[MODEL],
            device_type=SENSOR,  # because we send everything to boneio/sensor from modbus.
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            entity_id=self.name,
            mode="box",
            command_topic=f"{self.config.get_topic_prefix()}/cmd/modbus/{self._parent[ID].lower()}/set",
            command_template='{"device": "'
            + self.decoded_name
            + '", "value": "{{ value }}"}',
        )

    def encode_value(self, value: float) -> int:
        if self._write_filters:
            value = self._apply_filters(value=int(value), filters=self._write_filters)
        return int(value)
