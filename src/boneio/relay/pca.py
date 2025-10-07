"""PCA9685 PWM module."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from adafruit_pca9685 import PCA9685, PWMChannel

from boneio.relay.basic import BasicRelay

_LOGGER = logging.getLogger(__name__)


@dataclass(kw_only=True)
class PWMPCA(BasicRelay):
    """Initialize PWMPCA."""

    pca: PCA9685
    percentage_default_brightness: int = 1
    restored_brightness: int = 0

    def __post_init__(self) -> None:
        """Initialize PWMPCA."""
        super().__post_init__()
        self._pin: PWMChannel = self.pca.channels[self.pin_id]
        self._brightness = self.restored_brightness if self.restored_state else 0
        _LOGGER.debug("Setup PCA with pin %s", self.pin_id)

    @property
    def brightness(self) -> int:
        """Get brightness in 0-65535 scale. PCA can force over 65535 value after restart, so we treat that as a 0"""
        try:
            if self._pin.duty_cycle > 65535:
                return 0
            return self._pin.duty_cycle
        except KeyError:
            _LOGGER.error("Cant read value form driver on pin %s", self.pin_id)
            return 0

    def set_brightness(self, value: int) -> None:
        try:
            """Set brightness in 0-65535 vale"""
            _LOGGER.debug("Set brightness relay %s.", value)
            self._pin.duty_cycle = value
        except KeyError:
            _LOGGER.error("Cant set value form driver on pin %s", self.pin_id)

    def is_active(self) -> bool:
        """Is relay active."""
        return self.brightness > 1

    def _turn_on(self) -> None:
        """Call turn on action. When brightness is 0, and turn on by switch, default set value to 1%"""
        if self.brightness == 0:
            self.set_brightness(int(65535 / 100 * self.percentage_default_brightness))

    def _turn_off(self) -> None:
        """Call turn off action."""
        self._pin.duty_cycle = 0

    def payload(self) -> dict[str, int | Literal["ON", "OFF"]]:
        return {"brightness": self.brightness, "state": self.state}
