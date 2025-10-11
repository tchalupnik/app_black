"""Manage BoneIO onboard temp sensors."""

from __future__ import annotations

import logging
import time
import typing
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import timedelta

from boneio.events import EventBus, SensorEvent
from boneio.helper.filter import Filter
from boneio.models import SensorState

if typing.TYPE_CHECKING:
    from boneio.message_bus.basic import MessageBus

_LOGGER = logging.getLogger(__name__)


@dataclass
class TempSensor(ABC):
    """Represent Temp sensor in BoneIO."""

    id: str
    message_bus: MessageBus
    event_bus: EventBus
    send_topic: str
    name: str
    update_interval: timedelta
    filter: Filter
    unit_of_measurement: str
    last_timestamp: float = field(default_factory=time.time, init=False)
    _state: float | None = field(default=None, init=False)

    @abstractmethod
    def get_temperature(self) -> float:
        """Get temperature from sensor."""

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
        self.event_bus.trigger_event(
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
            topic=self.send_topic,
            payload={"state": self._state},
        )
