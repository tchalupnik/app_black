"""LM75 temp sensor."""

from datetime import timedelta

from adafruit_pct2075 import PCT2075
from busio import I2C

from boneio.config import Filters
from boneio.helper.exceptions import I2CError
from boneio.manager import Manager
from boneio.message_bus.basic import MessageBus

from . import TempSensor


class LM75Sensor(TempSensor):
    """Represent MCP9808 sensor in BoneIO."""

    def __init__(
        self,
        id: str,
        i2c: I2C,
        address: int,
        manager: Manager,
        message_bus: MessageBus,
        topic_prefix: str,
        name: str,
        update_interval: timedelta,
        filters: list[dict[Filters, float]],
        unit_of_measurement: str,
    ):
        """Initialize Temp class."""
        super().__init__(
            id=id,
            manager=manager,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            name=name,
            update_interval=update_interval,
            filters=filters,
            unit_of_measurement=unit_of_measurement,
        )
        try:
            self.pct = PCT2075(i2c, address)
        except ValueError as err:
            raise I2CError(err)

    def get_temperature(self) -> float:
        return self.pct.temperature
