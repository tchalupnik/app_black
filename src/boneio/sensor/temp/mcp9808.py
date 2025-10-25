"""MCP9808 temp sensor."""

from __future__ import annotations

import logging
import typing
from dataclasses import dataclass

from adafruit_mcp9808 import MCP9808

from boneio.helper.exceptions import I2CError

from . import TempSensor

if typing.TYPE_CHECKING:
    from busio import I2C


_LOGGER = logging.getLogger(__name__)


@dataclass
class MCP9808Sensor(TempSensor):
    """Represent MCP9808 sensor in BoneIO."""

    i2c: I2C
    address: int

    def __post_init__(self) -> None:
        """Initialize Temp class."""

        try:
            self.pct = MCP9808(self.i2c, self.address)
        except ValueError as err:
            raise I2CError(err)

    def get_temperature(self) -> float:
        try:
            return float(self.pct.temperature)
        except OSError as e:
            _LOGGER.warning("Error while getting a temperature! Error=%s", str(e))
            return 0.0
