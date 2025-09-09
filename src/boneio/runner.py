"""Runner code for boneIO. Based on HA runner."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import warnings


from boneio.const import (
    ADC,
    BINARY_SENSOR,
    COVER,
    DALLAS,
    DS2482,
    EVENT_ENTITY,
    INA219,
    LM75,
    MCP23017,
    MCP_TEMP_9808,
    MODBUS,
    OLED,
    ONEWIRE,
    OUTPUT_GROUP,
    PCA9685,
    PCF8575,
)
from boneio.helper import StateManager
from boneio.config import Config
from boneio.helper.events import EventBus, GracefulExit
from boneio.helper.exceptions import RestartRequestException
from boneio.manager import Manager
from boneio.message_bus import MQTTClient
from boneio.webui.web_server import WebServer

# Filter out cryptography deprecation warning
warnings.filterwarnings("ignore", category=DeprecationWarning, module="cryptography")

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
    mqttusername: str | None = None,
    mqttpassword: str | None = None,
    debug: int = 0,
) -> int:
    """Run BoneIO."""
    configuration = Config.model_validate(config)
    web_server = None
    tasks: set[asyncio.Task] = set()
    event_bus = EventBus(loop=asyncio.get_event_loop())
    shutdown_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    if debug >= 2:
        loop.set_debug(True)

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

    # Initialize message bus based on config
    if configuration.mqtt is not None:
        if mqttusername is not None:
            configuration.mqtt.username = mqttusername
        if mqttpassword is not None:
            configuration.mqtt.password = mqttpassword
        message_bus = MQTTClient(
            config=configuration,
        )
    else:
        from boneio.message_bus import LocalMessageBus

        message_bus = LocalMessageBus()

    manager_kwargs = {
        item["name"]: config.get(item["name"], item["default"])
        for item in config_modules
    }

    manager = Manager(
        config=configuration,
        message_bus=message_bus,
        event_bus=event_bus,
        event_pins=config.get(EVENT_ENTITY, []),
        binary_pins=config.get(BINARY_SENSOR, []),
        config_file_path=config_file,
        state_manager=StateManager(
            state_file=f"{os.path.split(config_file)[0]}state.json"
        ),
        sensors={
            LM75: configuration.lm75 or [],
            INA219: configuration.ina219 or [],
            MCP_TEMP_9808: configuration.mcp9808 or [],
            ONEWIRE: configuration.sensors or [],
        },
        modbus_devices=config.get("modbus_devices", {}),
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
    if configuration.web is not None:
        _LOGGER.info("Starting Web server.")
        web_server = WebServer(
            config=configuration,
            config_file=config_file,
            manager=manager,
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
        await asyncio.wait(
            [main_gather, asyncio.create_task(shutdown_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if shutdown_event.is_set():
            _LOGGER.info("Starting graceful shutdown...")
            await message_bus.announce_offline()
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
    except BaseException as e:
        _LOGGER.error(f"Unexpected BaseException: {type(e).__name__} - {e}")
    finally:
        _LOGGER.info("Cleaning up resources...")

        # Trigger web server shutdown if it's running
        if web_server and hasattr(web_server, "trigger_shutdown"):
            try:
                _LOGGER.info("Requesting web server shutdown...")
                await web_server.trigger_shutdown()
            except Exception as e:
                _LOGGER.error(f"Error triggering web server shutdown: {e}")

        # Stop the event bus
        event_bus.request_stop()

        # Create a copy of tasks set to avoid modification during iteration
        remaining_tasks = list(tasks)
        if remaining_tasks:
            # Cancel and wait for all remaining tasks
            # Web server task will be cancelled here if it hasn't finished after trigger_shutdown
            for task in remaining_tasks:
                if not task.done():
                    _LOGGER.debug(
                        f"Cancelling task: {task.get_name() if hasattr(task, 'get_name') else task}"
                    )
                    task.cancel()

            # Wait for all tasks to complete
            try:
                await asyncio.gather(*remaining_tasks, return_exceptions=True)
            except Exception as e:
                _LOGGER.error(f"Error during cleanup: {type(e).__name__} - {e}")

        _LOGGER.info("Shutdown complete")
        return 0
