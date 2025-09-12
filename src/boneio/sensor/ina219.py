"""INA219 Black sensor."""

from __future__ import annotations

import asyncio
import logging
import time
import typing
from datetime import datetime, timedelta

from boneio.config import Ina219Config, Ina219DeviceClass
from boneio.const import SENSOR, STATE
from boneio.helper import AsyncUpdater, BasicMqtt
from boneio.helper.filter import Filter
from boneio.helper.sensor.ina_219_smbus import INA219_I2C
from boneio.models import SensorState

if typing.TYPE_CHECKING:
    from boneio.manager import Manager
    from boneio.message_bus.basic import MessageBus

_LOGGER = logging.getLogger(__name__)

unit_converter = {"current": "A", "power": "W", "voltage": "V"}


class _INA219Sensor(BasicMqtt, Filter):
    """Represent single value from INA219 as sensor."""

    def __init__(
        self,
        device_class: Ina219DeviceClass,
        filters: list,
        state: float | None,
        id: str,
        name: str,
        message_bus: MessageBus,
        topic_prefix: str,
    ) -> None:
        super().__init__(
            id=id,
            name=name,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            topic_type=SENSOR,
        )
        self._unit_of_measurement = unit_converter[device_class]
        self._device_class = device_class
        self._filters = filters
        self._raw_state = state
        self._timestamp = time.time()
        self._state = (
            self._apply_filters(value=self._raw_state) if self._raw_state else None
        )

    @property
    def raw_state(self) -> float | None:
        return self._raw_state

    @raw_state.setter
    def raw_state(self, value: float) -> None:
        self._raw_state = value

    @property
    def state(self) -> float | None:
        return self._state

    @property
    def device_class(self) -> Ina219DeviceClass:
        return self._device_class

    @property
    def unit_of_measurement(self) -> str:
        return self._unit_of_measurement

    @property
    def last_timestamp(self) -> float:
        return self._timestamp

    def update(self, timestamp: float) -> None:
        """Fetch sensor data periodically and send to MQTT."""
        _state = self._apply_filters(value=self._raw_state) if self._raw_state else None
        if not _state:
            return
        self._state = _state
        self._timestamp = timestamp
        self.message_bus.send_message(
            topic=self._send_topic,
            payload={STATE: self.state},
        )


class INA219(AsyncUpdater):
    """Represent INA219 sensors."""

    def __init__(
        self,
        address: int,
        id: str,
        manager: Manager,
        update_interval: timedelta,
        message_bus: MessageBus,
        topic_prefix: str,
        config: Ina219Config,
    ) -> None:
        """Setup INA219 Sensor"""
        self._loop = asyncio.get_event_loop()
        self._ina_219 = INA219_I2C(address=address)
        self._sensors: dict[Ina219DeviceClass, _INA219Sensor] = {}
        self.id = id
        for sensor in config.sensors:
            _id = f"{id}_{sensor.id.replace(' ', '')}"
            self._sensors[sensor.device_class] = _INA219Sensor(
                device_class=sensor.device_class,
                filters=sensor.filters,
                state=None,
                name=sensor.id,
                id=_id,
                message_bus=message_bus,
                topic_prefix=topic_prefix,
            )
        AsyncUpdater.__init__(self, manager=manager, update_interval=update_interval)
        _LOGGER.debug("Configured INA219 on address %s", address)

    @property
    def sensors(self) -> dict[Ina219DeviceClass, _INA219Sensor]:
        return self._sensors

    async def async_update(self, timestamp: datetime) -> None:
        """Fetch temperature periodically and send to MQTT."""
        for k, sensor in self._sensors.items():
            value = getattr(self._ina_219, k)
            _LOGGER.debug("Fetched INA219 value: %s %s", k, value)
            if sensor.raw_state != value:
                sensor.raw_state = value
                sensor.update(timestamp=timestamp)
                self.manager.event_bus.trigger_event(
                    {
                        "event_type": "sensor",
                        "entity_id": sensor.id,
                        "event_state": SensorState(
                            id=sensor.id,
                            name=sensor.name,
                            state=sensor.state,
                            unit=sensor.unit_of_measurement,
                            timestamp=sensor.last_timestamp,
                        ),
                    }
                )
