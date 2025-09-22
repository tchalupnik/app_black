from __future__ import annotations

# Typing imports that create a circular dependency
from typing import TYPE_CHECKING

from boneio.config import Config
from boneio.const import BINARY_SENSOR, ID, MODEL, NAME, SENSOR
from boneio.helper.ha_discovery import modbus_numeric_availabilty_message
from boneio.message_bus.basic import MessageBus
from boneio.modbus.sensor.base import ModbusBaseSensor

if TYPE_CHECKING:
    from ..coordinator import ModbusCoordinator


class ModbusBinaryWriteableEntityDiscrete(ModbusBaseSensor):
    _ha_type_ = BINARY_SENSOR

    def __init__(
        self,
        coordinator: ModbusCoordinator,
        name: str,
        parent: dict,
        register_address: int,
        base_address: int,
        message_bus: MessageBus,
        config: Config,
        unit_of_measurement: str | None = None,
        state_class: str | None = None,
        device_class: str | None = None,
        value_type: str | None = None,
        return_type: str | None = None,
        filters: list | None = None,
        user_filters: list | None = None,
        ha_filter: str = "",
        write_address: int | None = None,
        payload_off: str = "OFF",
        payload_on: str = "ON",
        write_filters: list | None = None,
    ):
        ModbusBaseSensor.__init__(
            self,
            name=name,
            parent=parent,
            unit_of_measurement=unit_of_measurement,
            state_class=state_class,
            device_class=device_class,
            value_type=value_type,
            return_type=return_type,
            filters=filters,
            message_bus=message_bus,
            config=config,
            user_filters=user_filters,
            ha_filter=ha_filter,
            register_address=register_address,
            base_address=base_address,
        )
        self._coordinator = coordinator
        self.write_address = write_address
        self._write_filters = write_filters
        self._payload_off = payload_off
        self._payload_on = payload_on

    def discovery_message(self):
        value_template = f"{{{{ value_json.{self.decoded_name} }}}}"
        msg = modbus_numeric_availabilty_message(
            topic=self.config.get_topic_prefix(),
            id=self._parent[ID],
            name=self._parent[NAME],
            state_topic_base=str(self.base_address),
            model=self._parent[MODEL],
            device_type=SENSOR,  # because we send everything to boneio/sensor from modbus.
            value_template=value_template,
            entity_id=self.name,
            payload_off=self._payload_off,
            payload_on=self._payload_on,
        )
        return msg
