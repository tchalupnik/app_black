from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

from boneio.const import (
    ADDRESS,
    BASE,
    ID,
    LENGTH,
    MODBUS_SENSOR,
    MODEL,
    NAME,
    OFFLINE,
    ONLINE,
    REGISTERS,
    SENSOR,
    STATE,
)
from boneio.helper import AsyncUpdater, BasicMqtt
from boneio.helper.config import ConfigHelper
from boneio.helper.events import EventBus
from boneio.helper.filter import Filter
from boneio.helper.util import open_json
from boneio.models import SensorState

from .client import VALUE_TYPES, Modbus
from .single_sensor import SingleAdditionalSensor, SingleSensor
from .utils import CONVERT_METHODS, REGISTERS_BASE

_LOGGER = logging.getLogger(__name__)


class ModbusCoordinator(BasicMqtt, AsyncUpdater, Filter):
    """Represent Modbus sensor in BoneIO."""

    SensorClass = None
    DefaultName = "ModbusSensor"

    def __init__(
        self,
        modbus: Modbus,
        address: str,
        model: str,
        sensors_filters: dict,
        config_helper: ConfigHelper,
        event_bus: EventBus,
        id: str = DefaultName,
        additional_data: dict = {},
        **kwargs,
    ):
        """Initialize Modbus sensor class."""
        super().__init__(
            id=id or address,
            topic_type=SENSOR,
            topic_prefix=config_helper.topic_prefix,
            **kwargs,
        )
        self._config_helper = config_helper
        self._modbus = modbus
        self._db = open_json(path=os.path.dirname(__file__), model=model)
        self._model = self._db[MODEL]
        self._address = address
        self._discovery_sent = False
        self._payload_online = OFFLINE
        self._sensors_filters = {
            k.lower(): v for k, v in sensors_filters.items()
        }
        self._modbus_sensors: List[Dict[str, SingleSensor]] = []
        self._additional_sensors: List[Dict[str, SingleAdditionalSensor]] = []
        self._additional_sensors_by_source_name: Dict[str, List[SingleAdditionalSensor]] = {}
        self._additional_data = additional_data
        # Standard sensors
        for index, data in enumerate(self._db[REGISTERS_BASE]):
            base = data[BASE]
            self._modbus_sensors.append({})
            for register in data[REGISTERS]:
                single_sensor = SingleSensor(
                    name=register.get("name"),
                    parent={
                        NAME: self._name,
                        ID: self._id,
                        MODEL: self._model,
                    },
                    register_address=register[ADDRESS],
                    base_address=base,
                    unit_of_measurement=register.get("unit_of_measurement"),
                    state_class=register.get("state_class"),
                    device_class=register.get("device_class"),
                    value_type=register.get("value_type"),
                    return_type=register.get("return_type", "regular"),
                    filters=register.get("filters", []),
                    message_bus=self._message_bus,
                    config_helper=self._config_helper,
                    ha_filter=register.get("ha_filter", "round(2)"),
                )
                single_sensor.set_user_filters(
                    self._sensors_filters.get(single_sensor.decoded_name, [])
                )
                self._modbus_sensors[index][
                    single_sensor.decoded_name
                ] = single_sensor

        # Additional sensors
        if "additional_sensors" in self._db:
            for additional in self._db["additional_sensors"]:
                config_keys = additional.get("config_keys", [])
                if not self._additional_data:
                    continue
                if not all(k in self._additional_data for k in config_keys):
                    continue
                source_sensor = None
                for sensors in self._modbus_sensors:
                    for s in sensors.values():
                        if s.decoded_name == additional["source"].replace("_", ""):
                            source_sensor = s
                            break
                if not source_sensor:
                    _LOGGER.warning("Source sensor '%s' for additional sensor '%s' not found.", additional["source"], additional["name"])
                    continue
                single_sensor = SingleAdditionalSensor(
                    name=additional["name"],
                    parent={NAME: self._name, ID: self._id, MODEL: self._model},
                    register_address=-1,
                    base_address=base,
                    unit_of_measurement=additional.get("unit_of_measurement", "m3"),
                    state_class=additional.get("state_class", "measurement"),
                    device_class=additional.get("device_class", "volume"),
                    value_type=None,
                    return_type=None,
                    filters=[],
                    message_bus=self._message_bus,
                    config_helper=self._config_helper,
                    ha_filter=additional.get("ha_filter", "round(2)"),
                    formula=additional.get("formula", ""),
                    context_config = { k: v for k,v in self._additional_data.items() if k in config_keys },
                )
                self._additional_sensors.append({single_sensor.decoded_name: single_sensor})
                if source_sensor.decoded_name not in self._additional_sensors_by_source_name:
                    self._additional_sensors_by_source_name[source_sensor.decoded_name] = []
                self._additional_sensors_by_source_name[source_sensor.decoded_name].append(single_sensor)
        _LOGGER.info(
            "Available single sensors for %s: %s",
            self._name,
            ", ".join(
                [
                    s.name
                    for sensors in self._modbus_sensors
                    for s in sensors.values()
                ]
            ),
        )
        if self._additional_sensors:
            _LOGGER.info(
                "Available additional sensors for %s: %s",
                self._name,
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
        try:
            AsyncUpdater.__init__(self, **kwargs)
        except Exception as e:
            _LOGGER.error("Error in AsyncUpdater: %s", e)

    def get_entity_by_name(self, name: str) -> Optional[SingleSensor]:
        """Return sensor by name."""
        for sensors in self._modbus_sensors:
            if name in sensors:
                return sensors.get(name)
        return None

    def get_all_entities(self) -> List[Dict[str, SingleSensor]]:
        return self._modbus_sensors

    def set_payload_offline(self):
        self._payload_online = OFFLINE

    def _send_discovery_for_all_registers(self) -> datetime:
        """Send discovery message to HA for each register."""
        for sensors in self._modbus_sensors:
            for sensor in sensors.values():
                sensor.send_ha_discovery()
        for sensors in self._additional_sensors:
            for sensor in sensors.values():
                sensor.send_ha_discovery()
        return datetime.now()

    async def check_availability(self) -> None:
        """Get first register and check if it's available."""
        if (
            not self._discovery_sent
            or (datetime.now() - self._discovery_sent).seconds > 3600
        ) and self._config_helper.topic_prefix:
            self._discovery_sent = False
            first_register_base = self._db[REGISTERS_BASE][0]
            register_method = first_register_base.get("register_type", "input")
            # Let's try fetch register 2 times in case something wrong with initial packet.
            for _ in [0, 1]:
                register = await self._modbus.read_and_decode(
                    unit=self._address,
                    address=first_register_base[REGISTERS][0][ADDRESS],
                    method=register_method,
                    payload_type=first_register_base[REGISTERS][0].get(
                        "value_type", "FP32"
                    ),
                )
                if register is not None:
                    self._discovery_sent = (
                        self._send_discovery_for_all_registers()
                    )
                    await asyncio.sleep(2)
                    break
            if not self._discovery_sent:
                _LOGGER.error(
                    "Discovery for %s not sent. First register not available.",
                    self._id,
                )

    def _evaluate_formula(self, formula: str, context: dict) -> float:
        """
        Evaluate the formula for additional sensor using provided context.
        Allowed names: X (value from source sensor), config (dict with config values)
        """
        code = compile(formula, "<string>", "eval")
        return eval(code, {"__builtins__": {}}, context)
    

    async def async_update(self, timestamp: float) -> Optional[float]:
        """Fetch state periodically and send to MQTT."""
        update_interval = self._update_interval.total_in_seconds
        await self.check_availability()
        for index, data in enumerate(self._db[REGISTERS_BASE]):
            values = await self._modbus.read_registers(
                unit=self._address,
                address=data[BASE],
                count=data[LENGTH],
                method=data.get("register_type", "input"),
            )
            if self._payload_online == OFFLINE and values:
                _LOGGER.info(
                    "Sending online payload about device %s.", self._name
                )
                self._payload_online = ONLINE
                self._message_bus.send_message(
                    topic=f"{self._config_helper.topic_prefix}/{self._id}/{STATE}",
                    payload=self._payload_online,
                )
            if not values:
                if update_interval < 600:
                    # Let's wait litte more for device.
                    update_interval = update_interval * 1.5
                else:
                    # Let's assume device is offline.
                    self.set_payload_offline()
                    self._message_bus.send_message(
                        topic=f"{self._config_helper.topic_prefix}/{self._id}/{STATE}",
                        payload=self._payload_online,
                    )
                    self._discovery_sent = False
                _LOGGER.warning(
                    "Can't fetch data from modbus device %s. Will sleep for %s seconds",
                    self.id,
                    update_interval,
                )
                return update_interval
            elif update_interval != self._update_interval.total_in_seconds:
                update_interval = self._update_interval.total_in_seconds
            output = {}
            current_modbus_sensors = self._modbus_sensors[index]
            for sensor in current_modbus_sensors.values():
                if not sensor.value_type:
                    # Go with old method. Remove when switch Sofar to new.
                    decoded_value = CONVERT_METHODS[sensor.return_type](
                        result=values,
                        base=sensor.base_address,
                        addr=sensor.address,
                    )
                else:
                    start_index = sensor.address - sensor.base_address
                    count = VALUE_TYPES[sensor.value_type]["count"]
                    payload = values.registers[
                        start_index : start_index + count
                    ]
                    try:
                        decoded_value = self._modbus.decode_value(
                            payload, sensor.value_type
                        )
                    except Exception as e:
                        _LOGGER.error(
                            "Decoding error for %s at address %s, base: %s, length: %s, error %s",
                            sensor.name,
                            sensor.address,
                            sensor.base_address,
                            data[LENGTH],
                            e,
                        )
                        decoded_value = None
                sensor.set_value(value=decoded_value, timestamp=timestamp)
                if self._additional_sensors and sensor.get_value() is not None:
                    if sensor.decoded_name in self._additional_sensors_by_source_name:
                        for additional_sensor in self._additional_sensors_by_source_name[sensor.decoded_name]:
                            context = {
                                "X": sensor.get_value(),
                                **additional_sensor.context
                            }
                            value = self._evaluate_formula(additional_sensor.formula, context)
                            additional_sensor.set_value(value=value, timestamp=timestamp)
                            output[additional_sensor.decoded_name] = additional_sensor.state
                output[sensor.decoded_name] = sensor.state
                await self._event_bus.async_trigger_event(
                    event_type=MODBUS_SENSOR,
                    entity_id=sensor.id,
                    event=SensorState(
                        id=sensor.id,
                        name=sensor.name,
                        state=sensor.state,
                        unit=sensor.unit_of_measurement,
                        timestamp=sensor.last_timestamp,
                    ),
                )
                
            self._timestamp = timestamp
            self._message_bus.send_message(
                topic=f"{self._send_topic}/{data[BASE]}",
                payload=output,
            )
        return update_interval
