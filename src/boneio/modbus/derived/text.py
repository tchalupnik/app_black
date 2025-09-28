from __future__ import annotations

from boneio.config import Config, ModbusDeviceData
from boneio.const import ID, MODEL, NAME, TEXT_SENSOR
from boneio.helper.ha_discovery import (
    HaModbusMessage,
    modbus_sensor_availabilty_message,
)
from boneio.message_bus.basic import MessageBus
from boneio.modbus.sensor.base import BaseSensor


class ModbusDerivedTextSensor(BaseSensor):
    _ha_type_ = TEXT_SENSOR

    def __init__(
        self,
        name: str,
        parent: dict,
        message_bus: MessageBus,
        context_config: ModbusDeviceData,
        config: Config,
        source_sensor_base_address: str,
        source_sensor_decoded_name: str,
        value_mapping: dict,
    ) -> None:
        BaseSensor.__init__(
            self,
            name=name,
            parent=parent,
            value_type=None,
            return_type=None,
            filters=[],
            message_bus=message_bus,
            config=config,
            user_filters=[],
            ha_filter="",
        )
        self.context = context_config
        self.base_address = source_sensor_base_address
        self.source_sensor_decoded_name = source_sensor_decoded_name
        self._value_mapping = value_mapping
        self.state = ""

    def discovery_message(self) -> HaModbusMessage:
        return modbus_sensor_availabilty_message(
            topic=self.config.get_topic_prefix(),
            id=self._parent[ID],
            name=self._parent[NAME],
            state_topic_base=str(self.base_address),
            model=self._parent[MODEL],
            value_template=f"{{{{ value_json.{self.decoded_name} }}}}",
            sensor_id=self.name,
        )

    def evaluate_state(
        self, source_sensor_value: int | float, timestamp: float
    ) -> None:
        self._timestamp = timestamp
        self.state = self._value_mapping.get(str(source_sensor_value), "Unknown")
