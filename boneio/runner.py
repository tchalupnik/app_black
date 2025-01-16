"""Runner code for boneIO. Based on HA runner."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import warnings
from typing import Any, Set

from boneio.const import (
    ADC,
    BINARY_SENSOR,
    BONEIO,
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
    NAME,
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
from boneio.helper.events import EventBus, GracefulExit
from boneio.helper.exceptions import RestartRequestException
from boneio.manager import Manager
from boneio.mqtt_client import MQTTClient
from boneio.webui.web_server import WebServer

# Filter out cryptography deprecation warning
warnings.filterwarnings('ignore', category=DeprecationWarning, module='cryptography')

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
    web_server = None
    tasks: Set[asyncio.Task] = set()
    event_bus = EventBus(loop=asyncio.get_event_loop())
    shutdown_event = asyncio.Event()
    loop = asyncio.get_event_loop()

    def signal_handler():
        """Handle shutdown signals."""
        _LOGGER.info("Received shutdown signal, initiating graceful shutdown...")
        shutdown_event.set()
        
    # Register signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    event_bus_task = asyncio.create_task(event_bus.start())
    tasks.add(event_bus_task)
    event_bus_task.add_done_callback(tasks.discard)

    main_config = config.get(BONEIO, {})
    _config_helper = ConfigHelper(
        name=main_config.get(NAME, BONEIO),
        topic_prefix=config.get(MQTT, {}).get(TOPIC_PREFIX, None),
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
        event_bus=event_bus,
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
    # Convert coroutines to Tasks
    message_bus.set_manager(manager=manager)

    tasks.update(manager.get_tasks())

    message_bus_type = "MQTT" if isinstance(message_bus, MQTTClient) else "Local"
    _LOGGER.info("Starting message bus %s.", message_bus_type)
    message_bus_task = asyncio.create_task(message_bus.start_client())
    tasks.add(message_bus_task)
    message_bus_task.add_done_callback(tasks.discard)
    
    # Start web server if configured
    if "web" in config:
        web_config = config.get("web") or {}
        _LOGGER.info("Starting Web server.")
        web_server = WebServer(
            config_file=config_file,
            config_helper=_config_helper,
            manager=manager,
            port=web_config.get("port", 8090),  
            auth=web_config.get("auth", {}),  
            logger=config.get("logger", {}),
            debug_level=debug
        )
        web_server_task = asyncio.create_task(web_server.start_webserver())
        tasks.add(web_server_task)
        web_server_task.add_done_callback(tasks.discard)
    else:
        _LOGGER.info("Web server not configured.")

    try:
        # Convert tasks set to list for main gather
        task_list = list(tasks)
        main_gather = asyncio.gather(*task_list)
        
        # Wait for either shutdown signal or main task completion
        await asyncio.wait([
            main_gather,
            asyncio.create_task(shutdown_event.wait())
        ], return_when=asyncio.FIRST_COMPLETED)

        if shutdown_event.is_set():
            _LOGGER.info("Starting graceful shutdown...")
            main_gather.cancel()
            try:
                await main_gather
            except asyncio.CancelledError:
                pass

        return 0
    except asyncio.CancelledError:
        _LOGGER.info("Main task cancelled")
    except (RestartRequestException, GracefulExit):
        _LOGGER.info("Restart or graceful exit requested")
    except Exception as e:
        _LOGGER.error(f"Unexpected error: {type(e).__name__} - {e}")
    finally:
        _LOGGER.info("Cleaning up resources...")
        # Stop the event bus
        event_bus.request_stop()
        
        # Create a copy of tasks set to avoid modification during iteration
        remaining_tasks = list(tasks)
        if remaining_tasks:
            # Cancel and wait for all remaining tasks
            for task in remaining_tasks:
                if not task.done():
                    task.cancel()
            
            # Wait for all tasks to complete
            try:
                await asyncio.gather(*remaining_tasks, return_exceptions=True)
            except Exception as e:
                _LOGGER.error(f"Error during cleanup: {type(e).__name__} - {e}")
        
        _LOGGER.info("Shutdown complete")
        return 0
