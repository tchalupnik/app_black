from __future__ import annotations

import logging
import time
import typing
from datetime import datetime, timezone
from pathlib import Path

import anyio

from boneio.config import Config, ModbusDeviceConfig
from boneio.events import EventBus, ModbusDeviceEvent
from boneio.helper.util import strip_accents
from boneio.message_bus.basic import MessageBus
from boneio.modbus.derived import (
    ModbusDerivedNumericSensor,
    ModbusDerivedSelect,
    ModbusDerivedSwitch,
    ModbusDerivedTextSensor,
)
from boneio.modbus.models import (
    ModbusDevice,
    NumericAdditionalSensor,
    SelectAdditionalSensor,
    SwitchAdditionalSensor,
    TextAdditionalSensor,
    ValueType,
)
from boneio.modbus.sensor import ModbusBinarySensor, ModbusNumericSensor
from boneio.modbus.sensor.base import BaseSensor
from boneio.modbus.sensor.text import ModbusTextSensor
from boneio.modbus.writeable.binary import ModbusBinaryWriteableEntityDiscrete
from boneio.modbus.writeable.numeric import (
    ModbusNumericWriteableEntity,
    ModbusNumericWriteableEntityDiscrete,
)
from boneio.models import SensorState

from .client import Modbus
from .utils import CONVERT_METHODS

_LOGGER = logging.getLogger(__name__)


class ModbusCoordinator:
    """Represent Modbus coordinator in BoneIO."""

    def __init__(
        self,
        device_config: ModbusDeviceConfig,
        modbus: Modbus,
        config: Config,
        event_bus: EventBus,
        message_bus: MessageBus,
    ):
        """Initialize Modbus coordinator class."""
        # TODO: FILTERS
        self.name = device_config.id
        self.id = device_config.identifier()
        self.send_topic = f"{config.get_topic_prefix()}/sensor/{strip_accents(self.id)}"
        self.config = config
        self.message_bus = message_bus
        self._modbus = modbus
        self.device = ModbusDevice.model_validate_json(
            (Path("modbus_devices") / f"{device_config.model}.json").read_text()
        )
        self.address = device_config.address
        self.update_interval = device_config.update_interval
        self.discovery_sent = False
        self.payload_online = "offline"
        self.sensors_filters = device_config.sensor_filters
        self._modbus_entities: list[
            dict[
                str,
                ModbusNumericSensor
                | ModbusNumericWriteableEntity
                | ModbusNumericWriteableEntityDiscrete,
            ]
        ] = []
        self._modbus_entities_by_name: dict[
            str,
            ModbusNumericSensor
            | ModbusNumericWriteableEntity
            | ModbusNumericWriteableEntityDiscrete,
        ] = {}
        self._additional_sensors: list[
            dict[
                str,
                ModbusDerivedNumericSensor
                | ModbusDerivedTextSensor
                | ModbusDerivedSelect
                | ModbusDerivedSwitch,
            ]
        ] = []
        self._additional_sensors_by_source_name: dict[
            str,
            list[
                ModbusDerivedNumericSensor
                | ModbusDerivedTextSensor
                | ModbusDerivedSelect
                | ModbusDerivedSwitch
            ],
        ] = {}
        self._additional_sensors_by_name: dict[
            str,
            ModbusDerivedNumericSensor
            | ModbusDerivedTextSensor
            | ModbusDerivedSelect
            | ModbusDerivedSwitch,
        ] = {}
        self._additional_data = device_config.data

        self.init_modbus_entities()
        # Additional sensors
        if self.device.additional_sensors:
            self.init_derived_sensors()

        _LOGGER.info(
            "Available single sensors for %s: %s",
            self.name,
            ", ".join(
                [s.name for sensors in self._modbus_entities for s in sensors.values()]
            ),
        )
        if self._additional_sensors:
            _LOGGER.info(
                "Available additional sensors for %s: %s",
                self.name,
                ", ".join(
                    [
                        s.name
                        for sensors in self._additional_sensors
                        for s in sensors.values()
                    ]
                ),
            )
        self._event_bus = event_bus
        self._event_bus.add_haonline_listener(target=self.set_payload_offline)

    def init_modbus_entities(self) -> None:
        # Standard sensors
        for index, data in enumerate(self.device.registers_base):
            for register in data.registers:
                entity_type = register.entity_type if register.entity_type else "sensor"
                if entity_type == "sensor":
                    single_sensor = ModbusNumericSensor(
                        name=register.name,
                        base_address=data.base,
                        register_address=register.address,
                        parent={
                            "name": self.name,
                            "id": self.id,
                            "model": self.device.model,
                        },
                        unit_of_measurement=register.unit_of_measurement,
                        state_class=register.state_class,
                        device_class=register.device_class,
                        value_type=register.value_type,
                        return_type=register.return_type,
                        filters=[
                            filter_dict.model_dump() for filter_dict in register.filters
                        ],
                        message_bus=self.message_bus,
                        config=self.config,
                        ha_filter=register.ha_filter,
                    )
                elif entity_type == "text_sensor":
                    single_sensor = ModbusTextSensor(
                        name=register.name,
                        base_address=data.base,
                        register_address=register.address,
                        parent={
                            "name": self.name,
                            "id": self.id,
                            "model": self.device.model,
                        },
                        unit_of_measurement=register.unit_of_measurement,
                        state_class=register.state_class,
                        device_class=register.device_class,
                        value_type=register.value_type,
                        return_type=register.return_type,
                        filters=[
                            filter_dict.model_dump() for filter_dict in register.filters
                        ],
                        message_bus=self.message_bus,
                        config=self.config,
                        value_mapping=register.x_mapping,
                    )
                elif entity_type == "binary_sensor":
                    single_sensor = ModbusBinarySensor(
                        name=register.name,
                        base_address=data.base,
                        register_address=register.address,
                        parent={
                            "name": self.name,
                            "id": self.id,
                            "model": self.device.model,
                        },
                        unit_of_measurement=register.unit_of_measurement,
                        state_class=register.state_class,
                        device_class=register.device_class,
                        value_type=register.value_type,
                        return_type=register.return_type,
                        filters=[
                            filter_dict.model_dump() for filter_dict in register.filters
                        ],
                        message_bus=self.message_bus,
                        config=self.config,
                        payload_on=register.payload_on,
                        payload_off=register.payload_off,
                    )
                elif entity_type == "writeable_sensor":
                    single_sensor = ModbusNumericWriteableEntity(
                        name=register.name,
                        base_address=data.base,
                        register_address=register.address,
                        parent={
                            "name": self.name,
                            "id": self.id,
                            "model": self.device.model,
                        },
                        unit_of_measurement=register.unit_of_measurement,
                        state_class=register.state_class,
                        device_class=register.device_class,
                        value_type=register.value_type,
                        return_type=register.return_type,
                        filters=[
                            filter_dict.model_dump() for filter_dict in register.filters
                        ],
                        message_bus=self.message_bus,
                        config=self.config,
                        coordinator=self,
                        write_filters=[
                            filter_dict.model_dump()
                            for filter_dict in register.write_filters
                        ],
                        write_address=register.write_address,
                        ha_filter=register.ha_filter,
                    )
                elif entity_type == "writeable_sensor_discrete":
                    single_sensor = ModbusNumericWriteableEntityDiscrete(
                        name=register.name,
                        base_address=data.base,
                        register_address=register.address,
                        parent={
                            "name": self.name,
                            "id": self.id,
                            "model": self.device.model,
                        },
                        unit_of_measurement=register.unit_of_measurement,
                        state_class=register.state_class,
                        device_class=register.device_class,
                        value_type=register.value_type,
                        return_type=register.return_type,
                        filters=[
                            filter_dict.model_dump() for filter_dict in register.filters
                        ],
                        message_bus=self.message_bus,
                        config=self.config,
                        write_address=register.write_address,
                        write_filters=[
                            filter_dict.model_dump()
                            for filter_dict in register.write_filters
                        ],
                        ha_filter=register.ha_filter,
                    )
                elif entity_type == "writeable_binary_sensor_discrete":
                    single_sensor = ModbusBinaryWriteableEntityDiscrete(
                        name=register.name,
                        base_address=data.base,
                        register_address=register.address,
                        parent={
                            "name": self.name,
                            "id": self.id,
                            "model": self.device.model,
                        },
                        unit_of_measurement=register.unit_of_measurement,
                        state_class=register.state_class,
                        device_class=register.device_class,
                        value_type=register.value_type,
                        return_type=register.return_type,
                        filters=[
                            filter_dict.model_dump() for filter_dict in register.filters
                        ],
                        message_bus=self.message_bus,
                        config=self.config,
                        write_address=register.write_address,
                        payload_on=register.payload_on,
                        payload_off=register.payload_off,
                        write_filters=[
                            filter_dict.model_dump()
                            for filter_dict in register.write_filters
                        ],
                    )
                else:
                    typing.assert_never(entity_type)
                if self.sensors_filters is not None:
                    single_sensor.set_user_filters(
                        self.sensors_filters.get(single_sensor.decoded_name, [])
                    )
                self._modbus_entities[index][single_sensor.decoded_name] = single_sensor

    def init_derived_sensors(self) -> None:
        for _additional in self.device.additional_sensors:
            additional = _additional.root
            source_sensor: BaseSensor | None = None
            for sensors in self._modbus_entities:
                for s in sensors.values():
                    if s.decoded_name == additional.source.replace("_", ""):
                        source_sensor = s
                        break
            if source_sensor is None:
                _LOGGER.warning(
                    "Source sensor '%s' for additional sensor '%s' not found.",
                    additional.source,
                    additional.name,
                )
                continue
            derived_sensor: BaseSensor
            if isinstance(additional, TextAdditionalSensor):
                derived_sensor = ModbusDerivedTextSensor(
                    name=additional.name,
                    parent={
                        "name": self.name,
                        "id": self.id,
                        "model": self.device.model,
                    },
                    base_address=source_sensor.base_address,
                    message_bus=self.message_bus,
                    config=self.config,
                    decoded_name=source_sensor.decoded_name,
                    value_mapping=additional.x_mapping,
                    register_address=source_sensor.register_address,
                    value_type=source_sensor.value_type,
                )
            elif isinstance(additional, NumericAdditionalSensor):
                if not all(k in self._additional_data for k in additional.config_keys):
                    _LOGGER.warning(
                        "Not all config keys %s for additional sensor %s are present in device config data.",
                        additional.config_keys,
                        additional.name,
                    )
                    continue
                derived_sensor = ModbusDerivedNumericSensor(
                    name=additional.name,
                    parent={
                        "name": self.name,
                        "id": self.id,
                        "model": self.device.model,
                    },
                    base_address=source_sensor.base_address,
                    decoded_name=source_sensor.decoded_name,
                    unit_of_measurement=additional.unit_of_measurement,
                    state_class=additional.state_class,
                    device_class=additional.device_class,
                    message_bus=self.message_bus,
                    config=self.config,
                    formula=additional.formula,
                    context_config=self._additional_data,
                    register_address=source_sensor.register_address,
                    value_type=source_sensor.value_type,
                )
            elif isinstance(additional, SelectAdditionalSensor):
                derived_sensor = ModbusDerivedSelect(
                    name=additional.name,
                    parent={
                        "name": self.name,
                        "id": self.id,
                        "model": self.device.model,
                    },
                    base_address=source_sensor.base_address,
                    message_bus=self.message_bus,
                    config=self.config,
                    decoded_name=source_sensor.decoded_name,
                    value_mapping=additional.x_mapping,
                    register_address=source_sensor.register_address,
                    value_type=source_sensor.value_type,
                )
            elif isinstance(additional, SwitchAdditionalSensor):
                derived_sensor = ModbusDerivedSwitch(
                    name=additional.name,
                    parent={
                        "name": self.name,
                        "id": self.id,
                        "model": self.device.model,
                    },
                    base_address=source_sensor.base_address,
                    message_bus=self.message_bus,
                    config=self.config,
                    decoded_name=source_sensor.decoded_name,
                    value_mapping=additional.x_mapping,
                    payload_off=additional.payload_off,
                    payload_on=additional.payload_on,
                    register_address=source_sensor.register_address,
                    value_type=source_sensor.value_type,
                )
            else:
                typing.assert_never(additional)

            self._additional_sensors.append(
                {derived_sensor.decoded_name: derived_sensor}
            )
            self._additional_sensors_by_name[derived_sensor.decoded_name] = (
                derived_sensor
            )
            if (
                derived_sensor.decoded_name
                not in self._additional_sensors_by_source_name
            ):
                self._additional_sensors_by_source_name[
                    derived_sensor.decoded_name
                ] = []
            self._additional_sensors_by_source_name[derived_sensor.decoded_name].append(
                derived_sensor
            )

    def get_entity_by_name(
        self, name: str
    ) -> (
        ModbusNumericSensor
        | ModbusNumericWriteableEntity
        | ModbusNumericWriteableEntityDiscrete
        | None
    ):
        """Return sensor by name."""
        for sensors in self._modbus_entities:
            if name in sensors:
                return sensors.get(name)
        return None

    def get_all_entities(
        self,
    ) -> list[
        dict[
            str,
            ModbusNumericSensor
            | ModbusNumericWriteableEntity
            | ModbusNumericWriteableEntityDiscrete,
        ]
    ]:
        return self._modbus_entities

    def set_payload_offline(self) -> None:
        self.payload_online = "offline"

    def _send_discovery_for_all_registers(self) -> None:
        """Send discovery message to HA for each register."""
        for sensors in self._modbus_entities:
            for sensor in sensors.values():
                sensor.send_ha_discovery()
        for sensors in self._additional_sensors:
            for sensor in sensors.values():
                sensor.send_ha_discovery()

    async def write_register(self, value: str | float | int, entity: str) -> None:
        _LOGGER.debug("Writing register %s for %s", value, entity)
        output: dict[str, float | int | str] = {}
        timestamp = time.time()
        derived_sensor = self._additional_sensors_by_name.get(entity)
        if derived_sensor is not None:
            source_sensor = self.get_entity_by_name(derived_sensor.decoded_name)
            if source_sensor is None:
                raise ValueError("Source sensor doesn't exist!")

            if source_sensor.write_address is None:
                _LOGGER.error(
                    "Source sensor %s has no write address", source_sensor.name
                )
                return
            encoded_value = derived_sensor.encode_value(value)
            status = await self._modbus.write_register(
                unit=self.address,
                address=source_sensor.write_address,
                value=encoded_value,
            )
            source_sensor.set_value(value=encoded_value, timestamp=timestamp)
            derived_sensor.evaluate_state(source_sensor.value, timestamp)
            _LOGGER.debug("Register written %s", status)
            output[derived_sensor.decoded_name] = derived_sensor.state
            output[source_sensor.decoded_name] = source_sensor.state
            self.message_bus.send_message(
                topic=f"{self.send_topic}/{source_sensor.base_address}",
                payload=output,
            )
            return
        modbus_sensor = self.get_entity_by_name(entity)
        if modbus_sensor is None:
            raise ValueError("This sensor doesn't exist!")
        if modbus_sensor.write_address is None:
            _LOGGER.error("Modbus sensor %s has no write address", modbus_sensor.name)
            return
        encoded_value = modbus_sensor.encode_value(value)
        status = await self._modbus.write_register(
            unit=self.address, address=modbus_sensor.write_address, value=encoded_value
        )
        modbus_sensor.set_value(value=encoded_value, timestamp=timestamp)
        if self._additional_sensors and modbus_sensor.value is not None:
            if modbus_sensor.decoded_name in self._additional_sensors_by_source_name:
                for additional_sensor in self._additional_sensors_by_source_name[
                    modbus_sensor.decoded_name
                ]:
                    additional_sensor.evaluate_state(modbus_sensor.value, timestamp)
                    output[additional_sensor.decoded_name] = additional_sensor.state
                output[modbus_sensor.decoded_name] = modbus_sensor.state
        self._event_bus.trigger_event(
            ModbusDeviceEvent(
                entity_id=modbus_sensor.id,
                event_state=SensorState(
                    id=modbus_sensor.id,
                    name=modbus_sensor.name,
                    state=modbus_sensor.state,
                    unit=modbus_sensor.unit_of_measurement,
                    timestamp=modbus_sensor.last_timestamp,
                ),
            )
        )
        self._timestamp = timestamp
        self.message_bus.send_message(
            topic=f"{self.send_topic}/{modbus_sensor.base_address}",
            payload=output,
        )
        _LOGGER.debug("Register written %s", status)

    async def check_availability(self) -> None:
        """Get first register and check if it's available."""
        if (
            not self.discovery_sent
            or (datetime.now(timezone.utc) - self.discovery_sent).seconds > 3600
        ) and self.config.get_topic_prefix():
            self.discovery_sent = False
            first_register_base = self.device.registers_base[0]
            # Let's try fetch register 2 times in case something wrong with initial packet.
            for _ in [0, 1]:
                await self._modbus.read_and_decode(
                    unit=self.address,
                    address=first_register_base.registers[0].address,
                    method=first_register_base.register_type,
                    payload_type=first_register_base.registers[0].value_type,
                )
                self._send_discovery_for_all_registers()
                self.discovery_sent = datetime.now(timezone.utc)
                await anyio.sleep(2)
                break
            if not self.discovery_sent:
                _LOGGER.error(
                    "Discovery for %s not sent. First register not available.",
                    self.id,
                )

    async def async_update(self, timestamp: float) -> None:
        """Fetch state periodically and send to MQTT."""
        update_interval = self.update_interval.total_seconds()
        await self.check_availability()
        for index, data in enumerate(self.device.registers_base):
            values = await self._modbus.read_registers(
                unit=self.address,
                address=data.base,
                count=data.length,
                register_type=data.register_type.value,
            )
            if self.payload_online == "offline" and values:
                _LOGGER.info("Sending online payload about device %s.", self.name)
                self.payload_online = "online"
                self.message_bus.send_message(
                    topic=f"{self.config.get_topic_prefix()}/{self.id}/state",
                    payload=self.payload_online,
                )
            if not values:
                if update_interval < 600:
                    # Let's wait litte more for device.
                    update_interval = update_interval * 1.5
                else:
                    # Let's assume device is offline.
                    self.set_payload_offline()
                    self.message_bus.send_message(
                        topic=f"{self.config.get_topic_prefix()}/{self.id}/state",
                        payload=self.payload_online,
                    )
                    self.discovery_sent = False
                _LOGGER.warning(
                    "Can't fetch data from modbus device %s. Will sleep for %s seconds",
                    self.id,
                    update_interval,
                )
                return
            elif update_interval != self.update_interval.total_seconds():
                update_interval = self.update_interval.total_seconds()
            output = {}
            current_modbus_entities = self._modbus_entities[index]
            for sensor in current_modbus_entities.values():
                if not sensor.value_type:
                    # Go with old method. Remove when switch Sofar to new.
                    decoded_value = CONVERT_METHODS[sensor.return_type](
                        result=values,
                        base=sensor.base_address,
                        addr=sensor.register_address,
                    )
                else:
                    start_index = sensor.register_address - sensor.base_address
                    count = {
                        ValueType.U_WORD: 1,
                        ValueType.S_WORD: 1,
                        ValueType.U_DWORD: 2,
                        ValueType.S_DWORD: 2,
                        ValueType.U_DWORD_R: 2,
                        ValueType.S_DWORD_R: 2,
                        ValueType.U_QWORD: 4,
                        ValueType.S_QWORD: 4,
                        ValueType.U_QWORD_R: 4,
                        ValueType.FP32: 2,
                        ValueType.FP32_R: 2,
                    }[sensor.value_type]
                    payload = values.registers[start_index : start_index + count]
                    try:
                        decoded_value = self._modbus.decode_value(
                            payload, sensor.value_type
                        )
                    except Exception as e:
                        _LOGGER.error(
                            "Decoding error for %s at address %s, base: %s, length: %s, error %s",
                            sensor.name,
                            sensor.register_address,
                            sensor.base_address,
                            data.length,
                            e,
                        )
                        continue
                sensor.set_value(value=decoded_value, timestamp=timestamp)
                if self._additional_sensors and sensor.value is not None:
                    if sensor.decoded_name in self._additional_sensors_by_source_name:
                        for (
                            additional_sensor
                        ) in self._additional_sensors_by_source_name[
                            sensor.decoded_name
                        ]:
                            additional_sensor.evaluate_state(sensor.value, timestamp)
                            output[additional_sensor.decoded_name] = (
                                additional_sensor.state
                            )
                output[sensor.decoded_name] = sensor.state
                self._event_bus.trigger_event(
                    ModbusDeviceEvent(
                        entity_id=sensor.id,
                        event_state=SensorState(
                            id=sensor.id,
                            name=sensor.name,
                            state=sensor.state,
                            unit=sensor.unit_of_measurement,
                            timestamp=sensor.last_timestamp,
                        ),
                    )
                )

            self._timestamp = timestamp
            self.message_bus.send_message(
                topic=f"{self.send_topic}/{data.base}",
                payload=output,
            )
