"""Serial Number sensor."""

from __future__ import annotations

import logging
import typing
from datetime import timedelta

from boneio.const import SENSOR
from boneio.helper import AsyncUpdater
from boneio.helper.stats import get_network_info
from boneio.helper.util import strip_accents
from boneio.message_bus.basic import MessageBus

if typing.TYPE_CHECKING:
    from boneio.manager import Manager

_LOGGER = logging.getLogger(__name__)


class SerialNumberSensor(AsyncUpdater):
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
        self.id = id.replace(" ", "")
        self.name = name
        self.message_bus = message_bus
        self._send_topic = f"{topic_prefix}/{SENSOR}/{strip_accents(self.id)}"
        self.state = None
        AsyncUpdater.__init__(
            self, manager=manager, update_interval=timedelta(minutes=60)
        )
        _LOGGER.debug("Configured serial number sensor")

    async def async_update(self, timestamp: float) -> None:
        """Fetch temperature periodically and send to MQTT."""
        network_info = get_network_info()
        if not network_info or "mac" not in network_info:
            return
        # Remove colons and take last 6 characters
        _state = network_info["mac"].replace(":", "")[-6:]
        self.state = f"blk{_state}"
        self._timestamp = timestamp
        self.message_bus.send_message(
            topic=self._send_topic,
            payload=self.state,
        )
