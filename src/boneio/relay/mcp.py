"""MCP23017 Relay module."""

import logging

from adafruit_mcp230xx.mcp23017 import MCP23017, DigitalInOut

from boneio.const import COVER, OFF, ON, SWITCH
from boneio.events import EventBus
from boneio.helper.interlock import SoftwareInterlockManager
from boneio.message_bus.basic import MessageBus
from boneio.relay.basic import BasicRelay

_LOGGER = logging.getLogger(__name__)


class MCPRelay(BasicRelay):
    """Represents MCP Relay output"""

    def __init__(
        self,
        pin: int,
        mcp: MCP23017,
        expander_id: str,
        message_bus: MessageBus,
        topic_prefix: str,
        id: str,
        interlock_manager: SoftwareInterlockManager,
        interlock_groups: list[str],
        name: str,
        event_bus: EventBus,
        output_type: str = SWITCH,
        restored_state: bool = False,
    ) -> None:
        """Initialize MCP relay."""
        self.pin: DigitalInOut = mcp.get_pin(pin)
        if output_type == COVER:
            """Just in case to not restore state of covers etc."""
            restored_state = False
        super().__init__(
            id=id,
            pin_id=pin,
            name=name,
            topic_prefix=topic_prefix,
            event_bus=event_bus,
            message_bus=message_bus,
            interlock_manager=interlock_manager,
            interlock_groups=interlock_groups,
            output_type=output_type,
            restored_state=restored_state,
            expander_id=expander_id,
        )

        self.init_with_check_if_can_restore_state(restored_state=restored_state)
        _LOGGER.debug("Setup MCP with pin %s", self.pin_id)

    def init_with_check_if_can_restore_state(self, restored_state: bool) -> None:
        if restored_state:
            if self._interlock_manager is not None and self._interlock_groups:
                if not self._interlock_manager.can_turn_on(
                    self, self._interlock_groups
                ):
                    _LOGGER.warning(
                        "Interlock active: cannot restore ON state for %s at startup",
                        self.pin_id,
                    )
                    restored_state = False
        self.pin.switch_to_output(value=restored_state)

    @property
    def is_active(self) -> bool:
        """Is relay active."""
        return self.pin.value

    def turn_on(self, time=None) -> None:
        """Call turn on action."""
        self.pin.value = True
        self._state = ON
        if not time:
            self._execute_momentary_turn(momentary_type=ON)

    def turn_off(self, time=None) -> None:
        """Call turn off action."""
        self.pin.value = False
        self._state = OFF
        if not time:
            self._execute_momentary_turn(momentary_type=OFF)
