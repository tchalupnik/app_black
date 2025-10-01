"""PCF8575 Relay module."""

import logging
from dataclasses import dataclass

from adafruit_pcf8575 import DigitalInOut

from boneio.helper.pcf8575 import PCF8575
from boneio.relay.basic import BasicRelay

_LOGGER = logging.getLogger(__name__)


@dataclass(kw_only=True)
class PCFRelay(BasicRelay):
    """Represents PCF Relay output"""

    pcf: PCF8575

    def __post_init__(self) -> None:
        """Initialize MCP relay."""
        self._pin: DigitalInOut = self.pcf.get_pin(self.pin_id)
        if self.output_type == "none":
            """Just in case to not restore state of covers etc."""
            restored_state = False
        self._pin.switch_to_output(value=restored_state)
        super().__post_init__()
        self._active_state = False
        _LOGGER.debug("Setup PCF with pin %s", self.pin_id)

    def is_active(self) -> bool:
        """Is relay active."""
        return self._pin.value

    def _turn_on(self) -> None:
        """Call turn on action."""
        self._pin.value = True

    def _turn_off(self) -> None:
        """Call turn off action."""
        self._pin.value = False
