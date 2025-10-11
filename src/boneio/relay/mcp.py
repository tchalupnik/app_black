"""MCP23017 Relay module."""

import logging
from dataclasses import dataclass

from adafruit_mcp230xx.mcp23017 import MCP23017, DigitalInOut

from boneio.relay.basic import BasicRelay

_LOGGER = logging.getLogger(__name__)


@dataclass(kw_only=True)
class MCPRelay(BasicRelay):
    """Represents MCP Relay output"""

    mcp: MCP23017

    def __post_init__(self) -> None:
        """Initialize MCP relay."""
        self._pin: DigitalInOut = self.mcp.get_pin(self.pin_id)
        if self.output_type == "cover":
            """Just in case to not restore state of covers etc."""
            self.restored_state = False

        if self.restored_state:
            if self.interlock_manager is not None and self.interlock_groups:
                if not self.interlock_manager.can_turn_on(self, self.interlock_groups):
                    _LOGGER.warning(
                        "Interlock active: cannot restore ON state for %s at startup",
                        self.pin_id,
                    )
                    self.restored_state = False
        super().__post_init__()
        self._pin.switch_to_output(value=self.restored_state)
        _LOGGER.debug("Setup MCP with pin %s", self.pin_id)

    def is_active(self) -> bool:
        """Is relay active."""
        return bool(self._pin.value)

    def _turn_on(self) -> None:
        """Call turn on action."""
        self._pin.value = True

    def _turn_off(self) -> None:
        """Call turn off action."""
        self._pin.value = False
