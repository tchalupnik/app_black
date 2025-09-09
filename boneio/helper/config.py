"""
Module to provide basic config options.
"""

from __future__ import annotations

from _collections_abc import dict_values

from boneio.const import (
    BINARY_SENSOR,
    BONEIO,
    BUTTON,
    COVER,
    EVENT_ENTITY,
    HOMEASSISTANT,
    LIGHT,
    NUMERIC,
    SELECT,
    SENSOR,
    SWITCH,
    TEXT_SENSOR,
    VALVE,
)
from boneio.helper.util import sanitize_mqtt_topic


class ConfigHelper:
    def __init__(
        self,
        topic_prefix: str,
        name: str = BONEIO,
        device_type: str = "boneIO Black",
        ha_discovery: bool = True,
        ha_discovery_prefix: str = HOMEASSISTANT,
        network_info: dict | None = None,
        is_web_active: bool = False,
    ) -> None:
        self._name = name
        sanitized_topic_prefix = (
            sanitize_mqtt_topic(topic_prefix)
            if topic_prefix
            else sanitize_mqtt_topic(name)
        )
        self._topic_prefix = sanitized_topic_prefix
        self._ha_discovery = ha_discovery
        self._ha_discovery_prefix = ha_discovery_prefix
        self._device_type = device_type
        self._autodiscovery_messages = {
            SWITCH: {},
            LIGHT: {},
            BINARY_SENSOR: {},
            SENSOR: {},
            COVER: {},
            BUTTON: {},
            EVENT_ENTITY: {},
            VALVE: {},
            TEXT_SENSOR: {},
            SELECT: {},
            NUMERIC: {},
        }
        self.manager_ready: bool = False
        self._network_info = network_info

    @property
    def network_info(self) -> dict:
        return self._network_info

    @property
    def topic_prefix(self) -> str:
        return self._topic_prefix

    @property
    def name(self) -> str:
        return self._name

    @property
    def ha_discovery(self) -> bool:
        return self._ha_discovery

    @property
    def ha_discovery_prefix(self) -> str:
        return self._ha_discovery_prefix

    @property
    def device_type(self) -> str:
        return self._device_type

    def is_topic_in_autodiscovery(self, topic: str) -> bool:
        topic_parts_raw = topic[len(f"{self._ha_discovery_prefix}/") :].split("/")
        ha_type = topic_parts_raw[0]
        if ha_type in self._autodiscovery_messages:
            if topic in self._autodiscovery_messages[ha_type]:
                return True
        return False

    @property
    def autodiscovery_msgs(self) -> dict_values:
        """Get autodiscovery messages"""
        output = {}
        for ha_type in self._autodiscovery_messages:
            output.update(self._autodiscovery_messages[ha_type])
        return output.values()
