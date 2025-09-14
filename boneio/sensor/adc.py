"""ADC GPIO BBB sensor."""

import logging
from pathlib import Path
from typing_extensions import Literal

from boneio.const import SENSOR
from boneio.helper import AsyncUpdater, BasicMqtt
from boneio.helper.filter import Filter

_LOGGER = logging.getLogger(__name__)

# for BBB it's 1.8V
REFERENCE_VOLTAGE = 1.8
# maximum value for 12 bit ADC (range 0-4095), 4095 = 1.8V
MAX_ADC_VALUE = 4095


class ADC:
    """ADC class to read values from ADC pins."""

    @staticmethod
    def setup() -> None:
        """Setup ADC."""
        pass

    @staticmethod
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


class GpioADCSensor(BasicMqtt, AsyncUpdater, Filter):
    """Represent Gpio ADC sensor."""

    def __init__(self, pin: str, filters: list, **kwargs) -> None:
        """Setup GPIO ADC Sensor"""
        super().__init__(topic_type=SENSOR, **kwargs)
        self._pin = pin
        self._state = None
        self._filters = filters
        AsyncUpdater.__init__(self, **kwargs)
        _LOGGER.debug("Configured sensor pin %s", self._pin)

    @property
    def state(self) -> float:
        """Give rounded value of temperature."""
        return self._state

    def update(self, timestamp: float) -> None:
        """Fetch temperature periodically and send to MQTT."""
        _state = self._apply_filters(value=ADC.read(self._pin))
        if not _state:
            return
        self._state = _state
        self._timestamp = timestamp
        self._message_bus.send_message(
            topic=self._send_topic,
            payload=self.state,
        )
