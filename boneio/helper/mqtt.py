"""Class to help initialize classes which uses mqtt send."""

from __future__ import annotations


from typing import Callable, Union, Optional
from boneio.helper.util import strip_accents


class BasicMqtt:
    """Basic MQTT class."""

    def __init__(
        self,
        id: str,
        topic_prefix: str,
        name: str,
        send_message: Callable[
            [str, Union[str, int, dict, None], Optional[bool]], None
        ],
        topic_type: str,
        **kwargs,
    ):
        """Initialize module."""
        self._id = id.replace(" ", "")
        self._name = name
        self._send_message = send_message
        topic_id = strip_accents(self.id)
        self._send_topic = f"{topic_prefix}/{topic_type}/{topic_id}"

    @property
    def id(self) -> str:
        """Id of the module."""
        return self._id

    @property
    def name(self) -> str:
        """Return name of the sensor."""
        return self._name
