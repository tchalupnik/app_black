"""Input classes."""

from .gpio_event_button_old import GpioEventButton as GpioEventButtonOld
from .gpio_event_button_new import GpioEventButtonNew
from .gpio_relay import GpioRelay
from .gpio_sensor_new import GpioInputBinarySensorNew
from .gpio_sensor_old import GpioInputBinarySensor as GpioInputBinarySensorOld
from .base import (
    edge_detect,
    read_input,
    setup_input,
    setup_output,
    write_output,
    configure_pin,
)


__all__ = [
    "GpioEventButtonOld",
    "GpioEventButtonNew",
    "GpioRelay",
    "GpioInputBinarySensorOld",
    "GpioInputBinarySensorNew",
    "edge_detect",
    "read_input",
    "setup_input",
    "setup_output",
    "write_output",
    "configure_pin",
]
