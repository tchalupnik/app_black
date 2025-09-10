"""Dallas temp sensor."""

from __future__ import annotations

import asyncio
import logging
import typing
from datetime import timedelta

from adafruit_ds18x20 import DS18X20
from w1thermsensor import (
    NoSensorFoundError,
    SensorNotReadyError,
    W1ThermSensorError,
)

from boneio.const import STATE, TEMPERATURE
from boneio.helper.exceptions import OneWireError
from boneio.helper.onewire import (
    AsyncBoneIOW1ThermSensor,
    OneWireAddress,
    OneWireBus,
)

from . import TempSensor

if typing.TYPE_CHECKING:
    from boneio.manager import Manager
    from boneio.message_bus.basic import MessageBus


_LOGGER = logging.getLogger(__name__)


class DallasSensorDS2482(TempSensor):
    DefaultName = TEMPERATURE
    SensorClass = DS18X20

    def __init__(
        self,
        bus: OneWireBus,
        address: OneWireAddress,
        manager: Manager,
        message_bus: MessageBus,
        name: str,
        update_interval: timedelta,
        topic_prefix: str,
        id: str = DefaultName,
    ):
        """Initialize Temp class."""
        self._loop = asyncio.get_event_loop()
        # Use a dummy i2c and address since DS2482 doesn't use I2C
        super().__init__(
            i2c=None,
            address="",
            manager=manager,
            message_bus=message_bus,
            name=name,
            update_interval=update_interval,
            topic_prefix=topic_prefix,
            id=id,
        )
        try:
            self._pct = DS18X20(bus=bus, address=address)
            self._state = None
        except ValueError as err:
            raise OneWireError(err)


class DallasSensorW1(TempSensor):
    DefaultName = TEMPERATURE
    SensorClass = AsyncBoneIOW1ThermSensor

    def __init__(
        self,
        address: OneWireAddress,
        manager: Manager,
        message_bus: MessageBus,
        name: str,
        update_interval: timedelta,
        topic_prefix: str,
        id: str = DefaultName,
        filters: list = None,
    ):
        """Initialize Temp class."""
        if filters is None:
            filters = ["round(x, 2)"]
        self._loop = asyncio.get_event_loop()
        # Use a dummy i2c and address since W1 doesn't use I2C
        super().__init__(
            i2c=None,
            address="",
            manager=manager,
            message_bus=message_bus,
            name=name,
            update_interval=update_interval,
            topic_prefix=topic_prefix,
            id=id,
            filters=filters,
        )
        try:
            self._pct = AsyncBoneIOW1ThermSensor(sensor_id=address)
        except ValueError as err:
            raise OneWireError(err)

    async def async_update(self, timestamp: float) -> None:
        try:
            _temp = await self._pct.get_temperature()
            _LOGGER.debug("Fetched temperature %s. Applying filters.", _temp)
            _temp = self._apply_filters(value=_temp)
            if _temp is None:
                return
            self._state = _temp
            self._timestamp = timestamp
            self._message_bus.send_message(
                topic=self._send_topic,
                payload={STATE: self._state},
            )
        except SensorNotReadyError as err:
            _LOGGER.error("Sensor not ready, can't update %s", err)
        except NoSensorFoundError as err:
            _LOGGER.error("Sensor not found, can't update %s", err)
        except W1ThermSensorError as err:
            _LOGGER.error("Sensor not working, can't update %s", err)
