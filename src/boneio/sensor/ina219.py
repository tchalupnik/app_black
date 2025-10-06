"""INA219 Black sensor."""

from __future__ import annotations

import logging
import secrets
import time
import typing
from dataclasses import dataclass, field

from boneio.config import Ina219Config, Ina219DeviceClass
from boneio.events import EventBus, SensorEvent
from boneio.helper.filter import Filter
from boneio.helper.sensor.ina_219_smbus import INA219_I2C
from boneio.helper.util import strip_accents
from boneio.models import SensorState

if typing.TYPE_CHECKING:
    from boneio.message_bus import MessageBus

_LOGGER = logging.getLogger(__name__)

unit_converter = {"current": "A", "power": "W", "voltage": "V"}


@dataclass
class _INA219Sensor:
    """Represent single value from INA219 as sensor."""

    id: str
    name: str
    message_bus: MessageBus
    filter: Filter
    send_topic: str
    device_class: Ina219DeviceClass

    last_timestamp: float = field(default_factory=time.time, init=False)
    state: float | None = field(default=None, init=False)
    raw_state: float | None = field(default=None, init=False)

    @property
    def unit_of_measurement(self) -> str:
        return unit_converter[self.device_class]

    def __post_init__(
        self,
    ) -> None:
        if self.raw_state is not None:
            self.state = self.filter.apply_filters(value=self.raw_state)

    def update(self, timestamp: float) -> None:
        """Fetch sensor data periodically and send to MQTT."""
        state = (
            self.filter.apply_filters(value=self.raw_state) if self.raw_state else None
        )
        if state is None:
            return
        self.state = state
        self.last_timestamp = timestamp
        self.message_bus.send_message(
            topic=self.send_topic,
            payload={"state": self.state},
        )


@dataclass
class INA219:
    """Represent INA219 sensors."""

    id: str
    event_bus: EventBus
    ina219_i2c: INA219_I2C
    sensors: dict[Ina219DeviceClass, _INA219Sensor]

    @classmethod
    def from_config(
        cls,
        config: Ina219Config,
        message_bus: MessageBus,
        event_bus: EventBus,
        topic_prefix: str,
    ) -> INA219:
        """Create instance from config."""
        sensors: dict[Ina219DeviceClass, _INA219Sensor] = {}

        for sensor in config.sensors:
            sensor_id = (
                sensor.id.replace(" ", "") if sensor.id else secrets.token_urlsafe(4)
            )
            _id = f"{config.identifier()}_{sensor_id}"
            sensors[sensor.device_class] = _INA219Sensor(
                id=_id.replace(" ", ""),
                name=sensor_id,
                message_bus=message_bus,
                filters=Filter(sensor.filters),
                send_topic=f"{topic_prefix}/sensor/{strip_accents(_id)}",
                device_class=sensor.device_class,
            )
        this = INA219(
            id=config.identifier(),
            event_bus=event_bus,
            sensors=sensors,
            ina219_i2c=INA219_I2C(address=config.address),
        )
        _LOGGER.debug("Configured INA219 on address %s", config.address)
        return this

    def update(self, timestamp: float) -> None:
        """Fetch temperature periodically and send to MQTT."""
        for k, sensor in self.sensors.items():
            if k == "current":
                value = self.ina219_i2c.current
            elif k == "voltage":
                value = self.ina219_i2c.voltage
            elif k == "power":
                value = self.ina219_i2c.power
            else:
                typing.assert_never(k, "Unknown INA219 sensor")

            _LOGGER.debug("Fetched INA219 value: %s %s", k, value)
            if sensor.raw_state != value:
                sensor.raw_state = value
                sensor.update(timestamp=timestamp)
                self.event_bus.trigger_event(
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
