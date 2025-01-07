"""Runner code for boneIO. Based on HA runner."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from boneio.const import (
    ADC,
    BINARY_SENSOR,
    COVER,
    DALLAS,
    DS2482,
    ENABLED,
    EVENT_ENTITY,
    HA_DISCOVERY,
    HOST,
    INA219,
    LM75,
    MCP23017,
    MCP_TEMP_9808,
    MODBUS,
    MQTT,
    OLED,
    ONEWIRE,
    OUTPUT,
    OUTPUT_GROUP,
    PASSWORD,
    PCA9685,
    PCF8575,
    PORT,
    SENSOR,
    TOPIC_PREFIX,
    USERNAME,
)
from boneio.helper import StateManager
from boneio.helper.config import ConfigHelper
from boneio.manager import Manager
from boneio.mqtt_client import MQTTClient
from boneio.webui.web_server import WebServer

_LOGGER = logging.getLogger(__name__)

config_modules = [
    {"name": MCP23017, "default": []},
    {"name": PCF8575, "default": []},
    {"name": PCA9685, "default": []},
    {"name": DS2482, "default": []},
    {"name": ADC, "default": []},
    {"name": COVER, "default": []},
    {"name": MODBUS, "default": {}},
    {"name": OLED, "default": {}},
    {"name": DALLAS, "default": None},
    {"name": OUTPUT_GROUP, "default": []},
]


async def async_run(
    config: dict,
    config_file: str,
    mqttusername: str = "",
    mqttpassword: str = "",
    debug: int = 0
) -> list[Any]:
    """Run BoneIO."""
    _config_helper = ConfigHelper(
        topic_prefix=config.get(MQTT, {}).get(TOPIC_PREFIX, "boneio"),
        ha_discovery=config.get(MQTT, {}).get(HA_DISCOVERY, {}).get(ENABLED, False),
        ha_discovery_prefix=config.get(MQTT, {}).get(HA_DISCOVERY, {}).get(TOPIC_PREFIX, "homeassistant"),
    )

    # Initialize message bus based on config
    if MQTT in config:
        client = MQTTClient(
            host=config[MQTT][HOST],
            username=config[MQTT].get(USERNAME, mqttusername),
            password=config[MQTT].get(PASSWORD, mqttpassword),
            port=config[MQTT].get(PORT, 1883),
            config_helper=_config_helper,
        )
        message_bus = client
    else:
        from boneio.helper.message_bus import LocalMessageBus
        message_bus = LocalMessageBus()

    manager_kwargs = {
        item["name"]: config.get(item["name"], item["default"])
        for item in config_modules
    }

    manager = Manager(
        send_message=message_bus.send_message,
        stop_client=message_bus.stop,
        mqtt_state=message_bus.state,
        relay_pins=config.get(OUTPUT, []),
        event_pins=config.get(EVENT_ENTITY, []),
        binary_pins=config.get(BINARY_SENSOR, []),
        config_file_path=config_file,
        state_manager=StateManager(
            state_file=f"{os.path.split(config_file)[0]}state.json"
        ),
        config_helper=_config_helper,
        sensors={
            LM75: config.get(LM75, []),
            INA219: config.get(INA219, []),
            MCP_TEMP_9808: config.get(MCP_TEMP_9808, []),
            MODBUS: config.get("modbus_sensors"),
            ONEWIRE: config.get(SENSOR, []),
        },
        **manager_kwargs,
    )
    tasks = set()
    # Convert coroutines to Tasks
    tasks.update(manager.get_tasks())

    
    message_bus_type = "MQTT" if isinstance(message_bus, MQTTClient) else "Local"
    _LOGGER.info("Starting message bus %s.", message_bus_type)
    tasks.add(asyncio.create_task(message_bus.start_client(manager)))
    if "web" in config:
        web_config = config.get("web") or {}  # Convert None to empty dict
        port = web_config.get("port", 8090)
        auth = web_config.get("auth", {})
        web_server = WebServer(config_file=config_file, manager=manager, port=port, auth=auth, logger=config.get("logger", {}), debug_level=debug)
        tasks.add(asyncio.create_task(web_server.start_webserver()))
    result = await asyncio.gather(*tasks)
    return result
