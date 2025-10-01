"""Manage BoneIO onboard temp sensors."""

from __future__ import annotations

import logging
import time
import typing
from abc import ABC, abstractmethod
from datetime import timedelta

from boneio.config import Filters
from boneio.const import SENSOR
from boneio.events import SensorEvent
from boneio.helper import refresh_wrapper
from boneio.helper.filter import Filter
from boneio.helper.util import strip_accents
from boneio.models import SensorState

if typing.TYPE_CHECKING:
    from boneio.manager import Manager
    from boneio.message_bus.basic import MessageBus

_LOGGER = logging.getLogger(__name__)


class TempSensor(ABC):
    """Represent Temp sensor in BoneIO."""

    def __init__(
        self,
        id: str,
        manager: Manager,
        message_bus: MessageBus,
        topic_prefix: str,
        name: str,
        update_interval: timedelta,
        filters: list[dict[Filters, float]],
        unit_of_measurement: str,
    ):
        """Initialize Temp class."""
        if not filters:
            filters = [{"round": 2}]
        self.id = id.replace(" ", "")
        self.name = name
        self.message_bus = message_bus
        self.manager = manager
        self._send_topic = f"{topic_prefix}/{SENSOR}/{strip_accents(self.id)}"

        self.filter = Filter(filters)
        self.unit_of_measurement = unit_of_measurement
        self._state: float | None = None
        self.last_timestamp = time.time()
        manager.append_task(refresh_wrapper(self.update, update_interval), self.name)

    @abstractmethod
    def get_temperature(self) -> float:
        pass

    @property
    def state(self) -> float:
        """Give rounded value of temperature."""
        return self._state if self._state is not None else -1

    def update(self, timestamp: float) -> None:
        """Fetch temperature periodically and send to MQTT."""
        try:
            _temp = self.get_temperature()
            _LOGGER.debug("Fetched temperature %s. Applying filters.", _temp)
            _temp = self.filter.apply_filters(value=_temp)
        except RuntimeError as err:
            _LOGGER.error("Sensor error: %s %s", err, self.id)
            return
        self._state = _temp
        self.last_timestamp = timestamp
        self.manager.event_bus.trigger_event(
            SensorEvent(
                entity_id=self.id,
                event_state=SensorState(
                    id=self.id,
                    name=self.name,
                    state=self.state,
                    unit=self.unit_of_measurement,
                    timestamp=self.last_timestamp,
                ),
            )
        )
        self.message_bus.send_message(
            topic=self._send_topic,
            payload={"state": self._state},
        )
