from __future__ import annotations

from adafruit_pcf8575 import PCF8575 as AdafruitPCF8575
from busio import I2C


class PCF8575(AdafruitPCF8575):
    def __init__(self, i2c: I2C, address: int) -> None:
        super().__init__(i2c_bus=i2c, address=address)
