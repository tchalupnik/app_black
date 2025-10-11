"""Dallas temp sensor."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from adafruit_ds18x20 import DS18X20
from w1thermsensor import (
    NoSensorFoundError,
    SensorNotReadyError,
    W1ThermSensorError,
)

from boneio.helper.exceptions import OneWireError
from boneio.helper.onewire import (
    AsyncBoneIOW1ThermSensor,
    OneWireAddress,
    OneWireBus,
)

from . import TempSensor

_LOGGER = logging.getLogger(__name__)


@dataclass
class DallasSensorDS2482(TempSensor):
    bus: OneWireBus
    address: OneWireAddress

    def __post_init__(self) -> None:
        """Initialize Temp class."""
        try:
            self.pct = DS18X20(bus=self.bus, address=self.address.int_address)
        except ValueError as err:
            raise OneWireError(err)

    def get_temperature(self) -> float:
        return float(self.pct.read_temperature())


@dataclass
class DallasSensorW1(TempSensor):
    address: OneWireAddress

    def __post_init__(self) -> None:
        """Initialize Temp class."""
        try:
            self.pct = AsyncBoneIOW1ThermSensor(sensor_id=self.address)
        except ValueError as err:
            raise OneWireError(err)

    def get_temperature(self) -> float:
        try:
            _temp = self.pct.get_temperature()
            _LOGGER.debug("Fetched temperature %s. Applying filters.", _temp)
        except SensorNotReadyError as err:
            _LOGGER.error("Sensor not ready, can't update %s", err)
        except NoSensorFoundError as err:
            _LOGGER.error("Sensor not found, can't update %s", err)
        except W1ThermSensorError as err:
            _LOGGER.error("Sensor not working, can't update %s", err)
        return float(_temp)
