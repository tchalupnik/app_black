"""Class to help initialize classes which uses mqtt send."""

from __future__ import annotations

from pydantic import BaseModel

from boneio.helper.util import strip_accents
from boneio.message_bus.basic import MessageBus


class BasicMqtt:
    """Basic MQTT class."""

    def __init__(
        self,
        id: str,
        topic_prefix: str,
        name: str,
        message_bus: MessageBus,
        topic_type: str,
    ):
        """Initialize module."""
        self.id = id.replace(" ", "")
        self.name = name
        self.message_bus = message_bus
        self._send_topic = f"{topic_prefix}/{topic_type}/{strip_accents(self.id)}"


class MqttBase(BaseModel):
    # TODO: Finish later
    id: str
    topic_prefix: str
    topic_type: str
    # message_bus: MessageBus

    def send_topic(self) -> str:
        """Return the MQTT topic to send messages to."""
        topic_id = strip_accents(self.id.replace(" ", ""))
        return f"{self.topic_prefix}/{self.topic_type}/{topic_id}"
