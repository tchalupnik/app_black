"""Dallas temp sensor."""

from __future__ import annotations

import logging
import typing
from datetime import timedelta

from adafruit_ds18x20 import DS18X20
from w1thermsensor import (
    NoSensorFoundError,
    SensorNotReadyError,
    W1ThermSensorError,
)

from boneio.config import Filters
from boneio.const import STATE
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
    def __init__(
        self,
        bus: OneWireBus,
        address: OneWireAddress,
        manager: Manager,
        message_bus: MessageBus,
        name: str,
        update_interval: timedelta,
        topic_prefix: str,
        filters: list[dict[Filters, float]],
        id: str,
    ) -> None:
        """Initialize Temp class."""
        try:
            self.pct = DS18X20(bus=bus, address=address.int_address)
        except ValueError as err:
            raise OneWireError(err)

        super().__init__(
            manager=manager,
            message_bus=message_bus,
            name=name,
            update_interval=update_interval,
            topic_prefix=topic_prefix,
            id=id,
            filters=filters,
        )

    def get_temperature(self) -> float:
        return self.pct.read_temperature()


class DallasSensorW1(TempSensor):
    def __init__(
        self,
        address: OneWireAddress,
        manager: Manager,
        message_bus: MessageBus,
        name: str,
        update_interval: timedelta,
        topic_prefix: str,
        filters: list[dict[Filters, float]],
        id: str,
    ):
        """Initialize Temp class."""
        if not filters:
            filters = [{"round": 2}]

        try:
            self.pct = AsyncBoneIOW1ThermSensor(sensor_id=address)
        except ValueError as err:
            raise OneWireError(err)
        super().__init__(
            manager=manager,
            message_bus=message_bus,
            name=name,
            update_interval=update_interval,
            topic_prefix=topic_prefix,
            id=id,
            filters=filters,
        )

    def get_temperature(self) -> float:
        raise NotImplementedError("Uses its own async method")

    async def async_update(self, timestamp: float) -> None:
        try:
            _temp = await self.get_temperature()
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
