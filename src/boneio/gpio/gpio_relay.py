"""GPIO Relay module.
!!Not used in BoneIO.
Created just in case.
"""

import logging
from dataclasses import dataclass

from boneio.gpio_manager import GpioManagerBase
from boneio.relay.basic import BasicRelay

_LOGGER = logging.getLogger(__name__)


@dataclass(kw_only=True)
class GpioRelay(BasicRelay):
    """Represents GPIO Relay output"""

    gpio_manager: GpioManagerBase

    def __post_init__(self) -> None:
        """Initialize Gpio relay."""
        super().__post_init__()
        self.gpio_manager.write(self.pin_id, "low")
        _LOGGER.debug("Setup relay with pin %s", self.pin_id)

    def is_active(self) -> bool:
        """Is relay active."""
        return self.gpio_manager.read(self.pin_id)

    def _turn_on(self) -> None:
        """Call turn on action."""
        self.gpio_manager.write(self.pin_id, "high")

    def _turn_off(self) -> None:
        """Call turn off action."""
        self.gpio_manager.write(self.pin_id, "low")
