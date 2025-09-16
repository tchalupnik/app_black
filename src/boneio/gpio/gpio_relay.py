"""GPIO Relay module.
!!Not used in BoneIO.
Created just in case.
"""

import logging

from boneio.const import SWITCH
from boneio.gpio_manager import GpioManager
from boneio.helper.events import EventBus
from boneio.helper.interlock import SoftwareInterlockManager
from boneio.message_bus.basic import MessageBus
from boneio.relay.basic import BasicRelay

_LOGGER = logging.getLogger(__name__)


class GpioRelay(BasicRelay):
    """Represents GPIO Relay output"""

    def __init__(
        self,
        pin_id: int,
        message_bus: MessageBus,
        topic_prefix: str,
        id: str,
        interlock_manager: SoftwareInterlockManager,
        interlock_groups: list[str],
        name: str,
        event_bus: EventBus,
        gpio_manager: GpioManager,
        output_type: str = SWITCH,
        restored_state: bool = False,
    ) -> None:
        """Initialize Gpio relay."""
        super().__init__(
            id=id,
            pin_id=pin_id,
            name=name,
            topic_prefix=topic_prefix,
            event_bus=event_bus,
            message_bus=message_bus,
            interlock_manager=interlock_manager,
            interlock_groups=interlock_groups,
            output_type=output_type,
            restored_state=restored_state,
        )
        self.gpio_manager = gpio_manager
        self.gpio_manager.write(self.pin_id, "low")
        _LOGGER.debug("Setup relay with pin %s", self.pin_id)

    @property
    def is_active(self) -> bool:
        """Is relay active."""
        return self.gpio_manager.read(self.pin_id)

    def turn_on(self) -> None:
        """Call turn on action."""
        self.gpio_manager.write(self.pin_id, "high")

    def turn_off(self) -> None:
        """Call turn off action."""
        self.gpio_manager.write(self.pin_id, "low")
