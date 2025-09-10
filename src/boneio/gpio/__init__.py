"""Input classes."""

from .base import configure_pin
from .gpio_event_button_new import GpioEventButtonNew
from .gpio_event_button_old import GpioEventButton as GpioEventButtonOld
from .gpio_relay import GpioRelay
from .gpio_sensor_new import GpioInputBinarySensorNew
from .gpio_sensor_old import GpioInputBinarySensor as GpioInputBinarySensorOld

__all__ = [
    "GpioEventButtonOld",
    "GpioEventButtonNew",
    "GpioRelay",
    "GpioInputBinarySensorOld",
    "GpioInputBinarySensorNew",
    "configure_pin",
]
