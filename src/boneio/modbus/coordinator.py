from __future__ import annotations

import json
import logging
import time
import typing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import chain
from pathlib import Path
from typing import Literal

import anyio

from boneio.config import (
    Config,
    ModbusDeviceData,
    ModbusDeviceSensorFilters,
    ModbusModels,
)
from boneio.events import EventBus, ModbusDeviceEvent
from boneio.helper.filter import Filter
from boneio.helper.ha_discovery import HaAvailabilityTopic, HaDeviceInfo
from boneio.message_bus.basic import MessageBus, MqttAutoDiscoveryMessage
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
from boneio.modbus.sensor import (
    BaseSensor,
    ModbusBinarySensor,
    ModbusNumericSensor,
    ModbusTextSensor,
)
from boneio.modbus.writeable.binary import ModbusBinaryWriteableEntityDiscrete
from boneio.modbus.writeable.numeric import (
    ModbusNumericWriteableEntity,
    ModbusNumericWriteableEntityDiscrete,
)
from boneio.models import SensorState

from .client import Modbus

_LOGGER = logging.getLogger(__name__)


@dataclass
class ModbusCoordinator:
    """Represent Modbus coordinator in BoneIO."""

    id: str
    name: str
    send_topic: str
    address: int
    update_interval: timedelta
    sensors_filters: ModbusDeviceSensorFilters | None
    additional_data: ModbusDeviceData
    model: ModbusModels

    message_bus: MessageBus
    event_bus: EventBus
    modbus: Modbus
    config: Config

    discovery_sent: datetime | None = None
    state: Literal["offline", "online"] = "offline"

    modbus_entities: list[
        dict[
            str,
            BaseSensor,
        ]
    ] = field(init=False, default_factory=list)
    _modbus_entities_by_name: dict[
        str,
        ModbusNumericSensor
        | ModbusNumericWriteableEntity
        | ModbusNumericWriteableEntityDiscrete,
    ] = field(init=False, default_factory=dict)
    _additional_sensors: list[
        dict[
            str,
            ModbusDerivedNumericSensor
            | ModbusDerivedTextSensor
            | ModbusDerivedSelect
            | ModbusDerivedSwitch,
        ]
    ] = field(init=False, default_factory=list)
    _additional_sensors_by_source_name: dict[
        str,
        list[
            ModbusDerivedNumericSensor
            | ModbusDerivedTextSensor
            | ModbusDerivedSelect
            | ModbusDerivedSwitch
        ],
    ] = field(init=False, default_factory=dict)
    _additional_sensors_by_name: dict[
        str,
        ModbusDerivedNumericSensor
        | ModbusDerivedTextSensor
        | ModbusDerivedSelect
        | ModbusDerivedSwitch,
    ] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize Modbus coordinator class."""
        self.device = ModbusDevice.model_validate_json(
            (Path("modbus_devices") / f"{self.model}.json").read_text()
        )

        self.init_modbus_entities()
        # Additional sensors
        if self.device.additional_sensors:
            self.init_derived_sensors()

        _LOGGER.info(
            "Available single sensors for %s: %s",
            self.name,
            ", ".join(
                [s.name for sensors in self.modbus_entities for s in sensors.values()]
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
        self.event_bus.add_haonline_listener(target=self.set_payload_offline)

    def init_modbus_entities(self) -> None:
        # Standard sensors
        for index, data in enumerate(self.device.registers_base):
            self.modbus_entities.append({})
            for register in data.registers:
                entity_type = register.entity_type if register.entity_type else "sensor"
                single_sensor: BaseSensor
                if entity_type == "sensor":
                    single_sensor = ModbusNumericSensor(
                        name=register.name,
                        base_address=data.base,
                        register_address=register.address,
                        parent_id=self.id,
                        parent_name=self.name,
                        parent_model=self.device.model,
                        unit_of_measurement=register.unit_of_measurement,
                        state_class=register.state_class,
                        device_class=register.device_class,
                        value_type=register.value_type,
                        return_type=register.return_type,
                        filter=Filter(register.filters),
                        message_bus=self.message_bus,
                        ha_filter=register.ha_filter,
                    )
                elif entity_type == "text_sensor":
                    single_sensor = ModbusTextSensor(
                        name=register.name,
                        base_address=data.base,
                        register_address=register.address,
                        parent_id=self.id,
                        parent_name=self.name,
                        parent_model=self.device.model,
                        unit_of_measurement=register.unit_of_measurement,
                        state_class=register.state_class,
                        device_class=register.device_class,
                        value_type=register.value_type,
                        return_type=register.return_type,
                        filter=Filter(register.filters),
                        message_bus=self.message_bus,
                        value_mapping=register.x_mapping,
                    )
                elif entity_type == "binary_sensor":
                    single_sensor = ModbusBinarySensor(
                        name=register.name,
                        base_address=data.base,
                        register_address=register.address,
                        parent_id=self.id,
                        parent_name=self.name,
                        parent_model=self.device.model,
                        unit_of_measurement=register.unit_of_measurement,
                        state_class=register.state_class,
                        device_class=register.device_class,
                        value_type=register.value_type,
                        return_type=register.return_type,
                        filter=Filter(register.filters),
                        message_bus=self.message_bus,
                        payload_on=register.payload_on,
                        payload_off=register.payload_off,
                    )
                elif entity_type == "writeable_sensor":
                    single_sensor = ModbusNumericWriteableEntity(
                        name=register.name,
                        base_address=data.base,
                        register_address=register.address,
                        parent_id=self.id,
                        parent_name=self.name,
                        parent_model=self.device.model,
                        unit_of_measurement=register.unit_of_measurement,
                        state_class=register.state_class,
                        device_class=register.device_class,
                        value_type=register.value_type,
                        return_type=register.return_type,
                        filter=Filter(register.filters),
                        message_bus=self.message_bus,
                        write_filters=Filter(register.write_filters),
                        write_address=register.write_address,
                        ha_filter=register.ha_filter,
                    )
                elif entity_type == "writeable_sensor_discrete":
                    single_sensor = ModbusNumericWriteableEntityDiscrete(
                        name=register.name,
                        base_address=data.base,
                        register_address=register.address,
                        parent_id=self.id,
                        parent_name=self.name,
                        parent_model=self.device.model,
                        unit_of_measurement=register.unit_of_measurement,
                        state_class=register.state_class,
                        device_class=register.device_class,
                        value_type=register.value_type,
                        return_type=register.return_type,
                        filter=Filter(register.filters),
                        message_bus=self.message_bus,
                        write_address=register.write_address,
                        write_filters=Filter(register.write_filters),
                        ha_filter=register.ha_filter,
                    )
                elif entity_type == "writeable_binary_sensor_discrete":
                    single_sensor = ModbusBinaryWriteableEntityDiscrete(
                        name=register.name,
                        base_address=data.base,
                        register_address=register.address,
                        parent_id=self.id,
                        parent_name=self.name,
                        parent_model=self.device.model,
                        unit_of_measurement=register.unit_of_measurement,
                        state_class=register.state_class,
                        device_class=register.device_class,
                        value_type=register.value_type,
                        return_type=register.return_type,
                        filter=Filter(register.filters),
                        message_bus=self.message_bus,
                        write_address=register.write_address,
                        payload_on=register.payload_on,
                        payload_off=register.payload_off,
                        write_filters=Filter(register.write_filters),
                    )
                else:
                    typing.assert_never(entity_type)
                if self.sensors_filters is not None:
                    if single_sensor.decoded_name == "temperature":
                        filters = self.sensors_filters["temperature"]
                        single_sensor.user_filters = Filter(filters)
                    elif single_sensor.decoded_name == "humidity":
                        filters = self.sensors_filters["humidity"]
                        single_sensor.user_filters = Filter(filters)

                self.modbus_entities[index][single_sensor.decoded_name] = single_sensor

    def init_derived_sensors(self) -> None:
        for _additional in self.device.additional_sensors:
            additional = _additional.root
            source_sensor: BaseSensor | None = None
            for sensors in self.modbus_entities:
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
                    parent_id=self.id,
                    parent_name=self.name,
                    parent_model=self.device.model,
                    base_address=source_sensor.base_address,
                    message_bus=self.message_bus,
                    decoded_name=source_sensor.decoded_name,
                    value_mapping=additional.x_mapping,
                    register_address=source_sensor.register_address,
                    value_type=source_sensor.value_type,
                )
            elif isinstance(additional, NumericAdditionalSensor):
                if not all(k in self.additional_data for k in additional.config_keys):
                    _LOGGER.warning(
                        "Not all config keys %s for additional sensor %s are present in device config data.",
                        additional.config_keys,
                        additional.name,
                    )
                    continue
                derived_sensor = ModbusDerivedNumericSensor(
                    name=additional.name,
                    parent_id=self.id,
                    parent_name=self.name,
                    parent_model=self.device.model,
                    base_address=source_sensor.base_address,
                    decoded_name=source_sensor.decoded_name,
                    unit_of_measurement=additional.unit_of_measurement,
                    state_class=additional.state_class,
                    device_class=additional.device_class,
                    message_bus=self.message_bus,
                    formula=additional.formula,
                    context_config=self.additional_data,
                    register_address=source_sensor.register_address,
                    value_type=source_sensor.value_type,
                )
            elif isinstance(additional, SelectAdditionalSensor):
                derived_sensor = ModbusDerivedSelect(
                    name=additional.name,
                    parent_id=self.id,
                    parent_name=self.name,
                    parent_model=self.device.model,
                    base_address=source_sensor.base_address,
                    message_bus=self.message_bus,
                    decoded_name=source_sensor.decoded_name,
                    value_mapping=additional.x_mapping,
                    register_address=source_sensor.register_address,
                    value_type=source_sensor.value_type,
                )
            elif isinstance(additional, SwitchAdditionalSensor):
                derived_sensor = ModbusDerivedSwitch(
                    name=additional.name,
                    parent_id=self.id,
                    parent_name=self.name,
                    parent_model=self.device.model,
                    base_address=source_sensor.base_address,
                    message_bus=self.message_bus,
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

    def get_entity_by_name(self, name: str) -> BaseSensor | None:
        """Return sensor by name."""
        for sensors in self.modbus_entities:
            if name in sensors:
                return sensors.get(name)
        return None

    def set_payload_offline(self) -> None:
        self.state = "offline"

    def _send_discovery_for_all_registers(self) -> None:
        """Send discovery message to HA for each register."""
        if self.config.mqtt is None:
            return

        topic = self.config.get_topic_prefix()
        availability = [
            HaAvailabilityTopic(
                topic=f"{self.config.get_topic_prefix()}/{self.id}/state"
            )
        ]
        device_info = HaDeviceInfo(
            identifiers=[self.config.get_topic_prefix()],
            name=self.name,
            model=self.device.model,
        )

        for sensors in chain(self.modbus_entities, self._additional_sensors):
            assert isinstance(sensors, dict)
            for sensor in sensors.values():
                _LOGGER.debug(
                    "Sending %s discovery message for %s of %s",
                    sensor._ha_type_,
                    sensor.name,
                    sensor.parent_id,
                )
                self.message_bus.add_autodiscovery_message(
                    MqttAutoDiscoveryMessage(
                        type=sensor._ha_type_,
                        payload=sensor.discovery_message(
                            topic=topic,
                            device_info=device_info,
                            availability=availability,
                        ),
                        topic=f"{self.config.get_ha_autodiscovery_topic_prefix()}/{sensor._ha_type_.value.lower()}/{self.config.get_topic_prefix()}{sensor.parent_id}/{sensor.parent_id}{sensor.decoded_name.replace('_', '')}/config",
                    )
                )

    async def write_register(self, value: str | float | int, entity: str) -> None:
        _LOGGER.debug("Writing register %s for %s", value, entity)
        output: dict[str, float | int | str | None] = {}
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
            status = await self.modbus.write_register(
                unit=self.address,
                address=source_sensor.write_address,
                value=encoded_value,
            )
            source_sensor.set_state(value=encoded_value, timestamp=timestamp)
            derived_sensor.evaluate_state(source_sensor.state, timestamp)
            _LOGGER.debug("Register written %s", status)
            output[derived_sensor.decoded_name] = derived_sensor.state
            output[source_sensor.decoded_name] = source_sensor.state
            self.message_bus.send_message(
                topic=f"{self.send_topic}/{source_sensor.base_address}",
                payload=json.dumps(output),
            )
            return
        modbus_sensor = self.get_entity_by_name(entity)
        if modbus_sensor is None:
            raise ValueError("This sensor doesn't exist!")
        if modbus_sensor.write_address is None:
            _LOGGER.error("Modbus sensor %s has no write address", modbus_sensor.name)
            return
        encoded_value = modbus_sensor.encode_value(value)
        status = await self.modbus.write_register(
            unit=self.address, address=modbus_sensor.write_address, value=encoded_value
        )
        modbus_sensor.set_state(value=encoded_value, timestamp=timestamp)
        if self._additional_sensors and modbus_sensor.state is not None:
            if modbus_sensor.decoded_name in self._additional_sensors_by_source_name:
                for additional_sensor in self._additional_sensors_by_source_name[
                    modbus_sensor.decoded_name
                ]:
                    additional_sensor.evaluate_state(modbus_sensor.state, timestamp)
                    output[additional_sensor.decoded_name] = additional_sensor.state
                output[modbus_sensor.decoded_name] = modbus_sensor.state
        self.event_bus.trigger_event(
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
            payload=json.dumps(output),
        )
        _LOGGER.debug("Register written %s", status)

    async def check_availability(self) -> None:
        """Get first register and check if it's available."""
        if (
            self.discovery_sent is not None
            and (datetime.now(timezone.utc) - self.discovery_sent).seconds > 3600
        ) and self.config.get_topic_prefix():
            self.discovery_sent = None
            first_register_base = self.device.registers_base[0]
            # Let's try fetch register 2 times in case something wrong with initial packet.
            for _ in [0, 1]:
                await self.modbus.read_and_decode(
                    unit=self.address,
                    address=first_register_base.registers[0].address,
                    method=first_register_base.register_type,
                    payload_type=first_register_base.registers[0].value_type,
                )
                self._send_discovery_for_all_registers()
                self.discovery_sent = datetime.now(timezone.utc)
                await anyio.sleep(2)
                break
            if self.discovery_sent is not None:
                _LOGGER.error(
                    "Discovery for %s not sent. First register not available.",
                    self.id,
                )

    async def async_update(self, timestamp: float) -> None:
        """Fetch state periodically and send to MQTT."""
        update_interval = self.update_interval.total_seconds()
        await self.check_availability()
        for index, data in enumerate(self.device.registers_base):
            values = await self.modbus.read_registers(
                unit=self.address,
                address=data.base,
                count=data.length,
                register_type=data.register_type,
            )
            if self.state == "offline" and values:
                _LOGGER.info("Sending online message about device %s.", self.name)
                self.state = "online"
                self.message_bus.send_message(
                    topic=f"{self.config.get_topic_prefix()}/{self.id}/state",
                    payload=self.state,
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
                        payload=self.state,
                    )
                    self.discovery_sent = None
                _LOGGER.warning(
                    "Can't fetch data from modbus device %s. Will sleep for %s seconds",
                    self.id,
                    update_interval,
                )
                return
            elif update_interval != self.update_interval.total_seconds():
                update_interval = self.update_interval.total_seconds()
            output = {}
            current_modbus_entities = self.modbus_entities[index]
            for sensor in current_modbus_entities.values():
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
                    decoded_value = self.modbus.decode_value(payload, sensor.value_type)
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
                if isinstance(decoded_value, list):
                    _LOGGER.warning(
                        "Decoded value is list for sensor %s at address %s. Skipping.",
                        sensor.name,
                        sensor.register_address,
                    )
                    continue
                sensor.set_state(value=decoded_value, timestamp=timestamp)
                if self._additional_sensors and sensor.state is not None:
                    if sensor.decoded_name in self._additional_sensors_by_source_name:
                        for (
                            additional_sensor
                        ) in self._additional_sensors_by_source_name[
                            sensor.decoded_name
                        ]:
                            additional_sensor.evaluate_state(sensor.state, timestamp)
                            output[additional_sensor.decoded_name] = (
                                additional_sensor.state
                            )
                output[sensor.decoded_name] = sensor.state
                self.event_bus.trigger_event(
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
                payload=json.dumps(output),
            )
