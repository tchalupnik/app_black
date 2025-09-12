"""Serial Number sensor."""

from __future__ import annotations

import logging
import typing
from datetime import timedelta

from boneio.const import SENSOR
from boneio.helper import AsyncUpdater, BasicMqtt
from boneio.helper.stats import get_network_info
from boneio.message_bus.basic import MessageBus

if typing.TYPE_CHECKING:
    from boneio.manager import Manager

_LOGGER = logging.getLogger(__name__)


class SerialNumberSensor(BasicMqtt, AsyncUpdater):
    """Represent Serial Number sensor."""

    def __init__(
        self,
        id: str,
        name: str,
        manager: Manager,
        message_bus: MessageBus,
        topic_prefix: str,
    ) -> None:
        """Setup GPIO ADC Sensor"""
        super().__init__(
            topic_type=SENSOR,
            id=id,
            name=name,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
        )
        self._state = None
        AsyncUpdater.__init__(
            self, manager=manager, update_interval=timedelta(minutes=60)
        )
        _LOGGER.debug("Configured serial number sensor")

    @property
    def state(self) -> str:
        """Give rounded value of temperature."""
        return self._state

    async def async_update(self, timestamp: float) -> None:
        """Fetch temperature periodically and send to MQTT."""
        network_info = get_network_info()
        if not network_info or "mac" not in network_info:
            return
        # Remove colons and take last 6 characters
        _state = network_info["mac"].replace(":", "")[-6:]
        self._state = f"blk{_state}"
        self._timestamp = timestamp
        self.message_bus.send_message(
            topic=self._send_topic,
            payload=self.state,
        )
