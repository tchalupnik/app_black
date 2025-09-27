"""MCP23017 Relay module."""

import logging
from dataclasses import dataclass

from boneio.const import COVER
from boneio.relay.basic import BasicRelay

_LOGGER = logging.getLogger(__name__)


@dataclass
class MockRelay(BasicRelay):
    """Represents Mock Relay output"""

    def __post_init__(self) -> None:
        """Initialize Mock relay."""
        self.value = False
        if self.output_type == COVER:
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
        _LOGGER.debug("Setup Mock with pin %s", self.pin_id)

    def is_active(self) -> bool:
        """Is relay active."""
        return self.value

    def _turn_on(self) -> None:
        """Call turn on action."""
        self.value = True

    def _turn_off(self) -> None:
        """Call turn off action."""
        self.value = False
