"""INA219 Black sensor."""

from __future__ import annotations

import logging
import secrets
import time
import typing
from datetime import datetime

from boneio.config import Filters, Ina219Config, Ina219DeviceClass
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
        filters: list[dict[Filters, float]],
        id: str,
        name: str,
        message_bus: MessageBus,
        topic_prefix: str,
        state: float | None = None,
    ) -> None:
        super().__init__(
            id=id,
            name=name,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            topic_type=SENSOR,
        )
        self.unit_of_measurement = unit_converter[device_class]
        self.device_class = device_class
        self._filters = filters
        self.raw_state = state
        self.last_timestamp = time.time()
        self.state = (
            self._apply_filters(value=self.raw_state) if self.raw_state else None
        )

    def update(self, timestamp: float) -> None:
        """Fetch sensor data periodically and send to MQTT."""
        _state = self._apply_filters(value=self.raw_state) if self.raw_state else None
        if not _state:
            return
        self.state = _state
        self.last_timestamp = timestamp
        self.message_bus.send_message(
            topic=self._send_topic,
            payload={STATE: self.state},
        )


class INA219(AsyncUpdater):
    """Represent INA219 sensors."""

    def __init__(
        self,
        manager: Manager,
        message_bus: MessageBus,
        topic_prefix: str,
        config: Ina219Config,
    ) -> None:
        """Setup INA219 Sensor"""
        self._ina_219 = INA219_I2C(address=config.address)
        self.sensors: dict[Ina219DeviceClass, _INA219Sensor] = {}
        self.id = config.identifier()
        for sensor in config.sensors:
            sensor_id = (
                sensor.id.replace(" ", "") if sensor.id else secrets.token_urlsafe(4)
            )
            _id = f"{self.id}_{sensor_id}"
            self.sensors[sensor.device_class] = _INA219Sensor(
                device_class=sensor.device_class,
                filters=sensor.filters,
                name=sensor_id,
                id=_id,
                message_bus=message_bus,
                topic_prefix=topic_prefix,
            )
        AsyncUpdater.__init__(
            self, manager=manager, update_interval=config.update_interval
        )
        _LOGGER.debug("Configured INA219 on address %s", config.address)

    async def async_update(self, timestamp: datetime) -> None:
        """Fetch temperature periodically and send to MQTT."""
        for k, sensor in self.sensors.items():
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
