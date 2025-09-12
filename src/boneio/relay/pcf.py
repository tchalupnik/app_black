"""PCF8575 Relay module."""

import logging

from adafruit_pcf8575 import DigitalInOut

from boneio.const import NONE, OFF, ON, PCF, SWITCH
from boneio.helper.events import EventBus
from boneio.helper.interlock import SoftwareInterlockManager
from boneio.helper.pcf8575 import PCF8575
from boneio.message_bus.basic import MessageBus
from boneio.relay.basic import BasicRelay

_LOGGER = logging.getLogger(__name__)


class PCFRelay(BasicRelay):
    """Represents PCF Relay output"""

    def __init__(
        self,
        pin: int,
        expander: PCF8575,
        expander_id: str,
        message_bus: MessageBus,
        name: str,
        event_bus: EventBus,
        topic_prefix: str,
        id: str,
        interlock_manager: SoftwareInterlockManager,
        interlock_groups: list[str],
        output_type: str = SWITCH,
        restored_state: bool = False,
    ) -> None:
        """Initialize MCP relay."""
        self.pin: DigitalInOut = expander.get_pin(pin)
        if output_type == NONE:
            """Just in case to not restore state of covers etc."""
            restored_state = False
        self.pin.switch_to_output(value=restored_state)
        super().__init__(
            id=id,
            name=name,
            topic_prefix=topic_prefix,
            event_bus=event_bus,
            message_bus=message_bus,
            interlock_manager=interlock_manager,
            interlock_groups=interlock_groups,
            output_type=output_type,
            restored_state=restored_state,
        )
        self._expander_id = expander_id
        self._active_state = False
        _LOGGER.debug("Setup PCF with pin %s", self.pin_id)

    @property
    def is_active(self) -> bool:
        """Is relay active."""
        return self.pin.value == self._active_state

    def turn_on(self) -> None:
        """Call turn on action."""
        self.pin.value = self._active_state
        self._execute_momentary_turn(momentary_type=ON)

    def turn_off(self) -> None:
        """Call turn off action."""
        self.pin.value = not self._active_state
        self._execute_momentary_turn(momentary_type=OFF)
