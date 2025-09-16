"""ADC GPIO BBB sensor."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from boneio.const import SENSOR
from boneio.helper import AsyncUpdater
from boneio.helper.filter import Filter
from boneio.helper.util import strip_accents
from boneio.message_bus.basic import MessageBus

if TYPE_CHECKING:
    from boneio.manager import Manager

_LOGGER = logging.getLogger(__name__)

# for BBB it's 1.8V
REFERENCE_VOLTAGE = 1.8
# maximum value for 12 bit ADC (range 0-4095), 4095 = 1.8V
MAX_ADC_VALUE = 4095


def read(
    pin: Literal[
        "P9_39",
        "P9_40",
        "P9_37",
        "P9_38",
        "P9_33",
        "P9_36",
        "P9_35",
    ],
) -> float:
    """Read value from ADC pin."""
    filename = {
        "P9_39": "in_voltage0_raw",
        "P9_40": "in_voltage1_raw",
        "P9_37": "in_voltage2_raw",
        "P9_38": "in_voltage3_raw",
        "P9_33": "in_voltage4_raw",
        "P9_36": "in_voltage5_raw",
        "P9_35": "in_voltage6_raw",
    }.get(pin)

    if filename is None:
        _LOGGER.error("ADC pin %s is not valid.", pin)
        return 0.0

    path = Path("/sys/bus/iio/devices/iio:device0/" / filename)
    try:
        with path.open() as file:
            value = int(file.read().strip())
            return round((value / MAX_ADC_VALUE) * REFERENCE_VOLTAGE, 3)
    except Exception as ex:
        _LOGGER.error("Error reading ADC pin %s: %s", pin, ex)
        return 0.0


class GpioADCSensor(AsyncUpdater, Filter):
    """Represent Gpio ADC sensor."""

    def __init__(
        self,
        pin: str,
        filters: list,
        manager: Manager,
        update_interval: timedelta,
        id: str,
        name: str,
        message_bus: MessageBus,
        topic_prefix: str,
    ) -> None:
        """Setup GPIO ADC Sensor"""
        super().__init__(
            manager=manager,
            update_interval=update_interval,
        )
        self.id = id.replace(" ", "")
        self.name = name
        self.message_bus = message_bus
        self._send_topic = f"{topic_prefix}/{SENSOR}/{strip_accents(self.id)}"
        self._pin = pin
        self.state: float | None = None
        self._filters = filters
        AsyncUpdater.__init__(self, manager=manager, update_interval=update_interval)
        _LOGGER.debug("Configured sensor pin %s", self._pin)

    def update(self, timestamp: float) -> None:
        """Fetch temperature periodically and send to MQTT."""
        _state = self._apply_filters(value=read(self._pin))
        if not _state:
            return
        self.state = _state
        self._timestamp = timestamp
        self.message_bus.send_message(
            topic=self._send_topic,
            payload=self.state,
        )
