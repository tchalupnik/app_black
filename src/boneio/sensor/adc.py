"""ADC GPIO BBB sensor."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from boneio.config import AdcPins
from boneio.helper.filter import Filter
from boneio.helper.util import strip_accents
from boneio.message_bus.basic import MessageBus

_LOGGER = logging.getLogger(__name__)

# for BBB it's 1.8V
REFERENCE_VOLTAGE = 1.8
# maximum value for 12 bit ADC (range 0-4095), 4095 = 1.8V
MAX_ADC_VALUE = 4095


@dataclass
class GpioADCSensor:
    """Represent Gpio ADC sensor."""

    id: str
    pin: AdcPins
    filter: Filter
    message_bus: MessageBus
    topic_prefix: str
    state: float | None = field(default=None, init=False)

    def ___post_init__(
        self,
    ) -> None:
        """Setup GPIO ADC Sensor"""
        self.send_topic = f"{self.topic_prefix}/sensor/{strip_accents(self.id)}"
        filename: str | None = {
            "P9_39": "in_voltage0_raw",
            "P9_40": "in_voltage1_raw",
            "P9_37": "in_voltage2_raw",
            "P9_38": "in_voltage3_raw",
            "P9_33": "in_voltage4_raw",
            "P9_36": "in_voltage5_raw",
            "P9_35": "in_voltage6_raw",
        }.get(self.pin)
        if filename is None:
            raise ValueError("ADC pin %s is not valid.", self.pin)
        self.filename = filename
        _LOGGER.debug("Configured sensor pin %s", self.pin)

    def update(self, timestamp: float) -> None:
        """Fetch temperature periodically and send to MQTT."""
        self.state = self.filter.apply_filters(value=self.read())
        self._timestamp = timestamp
        self.message_bus.send_message(
            topic=self.send_topic, payload=json.dumps({"state": self.state})
        )

    def read(self) -> float:
        """Read value from ADC pin."""
        path = Path("/sys/bus/iio/devices/iio:device0/") / self.filename
        try:
            with path.open() as file:
                value = int(file.read().strip())
                return round((value / MAX_ADC_VALUE) * REFERENCE_VOLTAGE, 3)
        except Exception as ex:
            _LOGGER.error("Error reading ADC pin %s: %s", self.pin, ex)
            return 0.0
