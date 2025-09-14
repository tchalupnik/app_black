"""GPIO Relay module.
!!Not used in BoneIO.
Created just in case.
"""

import logging

from boneio.const import HIGH, LOW
from boneio.helper.gpiod import GpioManager
from boneio.relay.basic import BasicRelay

_LOGGER = logging.getLogger(__name__)


class GpioRelay(BasicRelay):
    """Represents GPIO Relay output"""

    def __init__(self, pin: str, gpio_manager: GpioManager, **kwargs) -> None:
        """Initialize Gpio relay."""
        super().__init(**kwargs)
        self._pin = pin
        self._gpio_manager = gpio_manager
        self._gpio_manager.write(self._pin, LOW)
        _LOGGER.debug("Setup relay with pin %s", self._pin)

    @property
    def is_active(self) -> bool:
        """Is relay active."""
        return self._gpio_manager.read(self._pin)

    @property
    def pin(self) -> str:
        """PIN of the relay"""
        return self._pin

    def turn_on(self) -> None:
        """Call turn on action."""
        self._gpio_manager.write(self._pin, HIGH)
        self._loop.call_soon_threadsafe(self.send_state)

    def turn_off(self) -> None:
        """Call turn off action."""
        self._gpio_manager.write(self._pin, LOW)
        self._loop.call_soon_threadsafe(self.send_state)
