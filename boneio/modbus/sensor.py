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
from .single_sensor import SingleSensor
from .utils import CONVERT_METHODS, REGISTERS_BASE

_LOGGER = logging.getLogger(__name__)


class ModbusSensor(BasicMqtt, AsyncUpdater, Filter):
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
                    send_message=self._send_message,
                    config_helper=self._config_helper,
                    ha_filter=register.get("ha_filter", "round(2)"),
                )
                single_sensor.set_user_filters(
                    self._sensors_filters.get(single_sensor.decoded_name, [])
                )
                self._modbus_sensors[index][
                    single_sensor.decoded_name
                ] = single_sensor
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
        self._event_bus = event_bus
        self._event_bus.add_haonline_listener(target=self.set_payload_offline)
        try:
            AsyncUpdater.__init__(self, **kwargs)
        except Exception as e:
            _LOGGER.error("Error in AsyncUpdater: %s", e)

    def get_sensor_by_name(self, name: str) -> Optional[SingleSensor]:
        """Return sensor by name."""
        for sensors in self._modbus_sensors:
            if name in sensors:
                return sensors.get(name)
        return None

    def get_all_sensors(self) -> List[Dict[str, SingleSensor]]:
        return self._modbus_sensors

    def set_payload_offline(self):
        self._payload_online = OFFLINE

    def _send_discovery_for_all_registers(self) -> datetime:
        """Send discovery message to HA for each register."""
        for sensors in self._modbus_sensors:
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
                self._send_message(
                    topic=f"{self._config_helper.topic_prefix}/{self._id}{STATE}",
                    payload=self._payload_online,
                )
            if not values:
                if update_interval < 600:
                    # Let's wait litte more for device.
                    update_interval = update_interval * 1.5
                else:
                    # Let's assume device is offline.
                    self.set_payload_offline()
                    self._send_message(
                        topic=f"{self._config_helper.topic_prefix}/{self._id}{STATE}",
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
            self._send_message(
                topic=f"{self._send_topic}/{data[BASE]}",
                payload=output,
            )
        return update_interval
