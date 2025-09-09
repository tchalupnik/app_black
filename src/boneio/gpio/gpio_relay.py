"""GPIO Relay module.
!!Not used in BoneIO.
Created just in case.
"""

import logging

from boneio.const import SWITCH
from boneio.gpio import read_input, setup_output, write_output
from boneio.helper.events import EventBus
from boneio.helper.interlock import SoftwareInterlockManager
from boneio.message_bus.basic import MessageBus
from boneio.relay.basic import BasicRelay

from .base import HIGH, LOW

_LOGGER = logging.getLogger(__name__)


class GpioRelay(BasicRelay):
    """Represents GPIO Relay output"""

    def __init__(
        self,
        pin: int,
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
        """Initialize Gpio relay."""
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
        )
        setup_output(self._pin_id)
        write_output(self._pin_id, LOW)
        _LOGGER.debug("Setup relay with pin %s", self._pin_id)

    @property
    def is_active(self) -> bool:
        """Is relay active."""
        return read_input(self._pin_id, on_state=HIGH)

    def turn_on(self) -> None:
        """Call turn on action."""
        write_output(self._pin_id, HIGH)

    def turn_off(self) -> None:
        """Call turn off action."""
        write_output(self._pin_id, LOW)
