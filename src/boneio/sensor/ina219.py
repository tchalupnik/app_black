"""INA219 Black sensor."""

from __future__ import annotations

import logging
import secrets
import time
import typing
from datetime import datetime

from boneio.config import Filters, Ina219Config, Ina219DeviceClass
from boneio.events import SensorEvent
from boneio.helper.filter import Filter
from boneio.helper.sensor.ina_219_smbus import INA219_I2C
from boneio.helper.util import strip_accents
from boneio.models import SensorState

if typing.TYPE_CHECKING:
    from boneio.manager import Manager
    from boneio.message_bus import MessageBus

_LOGGER = logging.getLogger(__name__)

unit_converter = {"current": "A", "power": "W", "voltage": "V"}


class _INA219Sensor:
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
        self.id = id.replace(" ", "")
        self.name = name
        self.message_bus = message_bus
        self._send_topic = f"{topic_prefix}/sensor/{strip_accents(self.id)}"
        self.unit_of_measurement = unit_converter[device_class]
        self.device_class = device_class
        self.filter = Filter(filters)
        self.raw_state = state
        self.last_timestamp = time.time()
        self.state = (
            self.filter.apply_filters(value=self.raw_state) if self.raw_state else None
        )

    def update(self, timestamp: float) -> None:
        """Fetch sensor data periodically and send to MQTT."""
        _state = (
            self.filter.apply_filters(value=self.raw_state) if self.raw_state else None
        )
        if not _state:
            return
        self.state = _state
        self.last_timestamp = timestamp
        self.message_bus.send_message(
            topic=self._send_topic,
            payload={"state": self.state},
        )


class INA219:
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
        self.manager = manager
        self.manager.append_task(self.update, config.update_interval)
        _LOGGER.debug("Configured INA219 on address %s", config.address)

    def update(self, timestamp: datetime) -> None:
        """Fetch temperature periodically and send to MQTT."""
        for k, sensor in self.sensors.items():
            value = getattr(self._ina_219, k)
            _LOGGER.debug("Fetched INA219 value: %s %s", k, value)
            if sensor.raw_state != value:
                sensor.raw_state = value
                sensor.update(timestamp=timestamp)
                self.manager.event_bus.trigger_event(
                    SensorEvent(
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
