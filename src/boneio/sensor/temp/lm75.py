"""LM75 temp sensor."""

from __future__ import annotations

import typing
from dataclasses import dataclass

from adafruit_pct2075 import PCT2075

from boneio.helper.exceptions import I2CError

from . import TempSensor

if typing.TYPE_CHECKING:
    from busio import I2C


@dataclass
class LM75Sensor(TempSensor):
    """Represent MCP9808 sensor in BoneIO."""

    i2c: I2C
    address: int

    def __post_init__(
        self,
    ) -> None:
        """Initialize Temp class."""

        try:
            self.pct = PCT2075(self.i2c, self.address)
        except ValueError as err:
            raise I2CError(err)

    def get_temperature(self) -> float:
        return float(self.pct.temperature)
