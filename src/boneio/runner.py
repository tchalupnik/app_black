"""Runner code for boneIO. Based on HA runner."""

from __future__ import annotations

import asyncio
import logging
import signal
import warnings
from contextlib import AsyncExitStack
from pathlib import Path

from boneio.config import Config
from boneio.events import EventBus
from boneio.gpio_manager import GpioManager
from boneio.logger import configure_logger
from boneio.manager import Manager
from boneio.message_bus import LocalMessageBus, MQTTClient
from boneio.webui.web_server import WebServer

# Filter out cryptography deprecation warning
warnings.filterwarnings("ignore", category=DeprecationWarning, module="cryptography")

_LOGGER = logging.getLogger(__name__)


async def async_run(
    config: Config,
    config_file: Path,
    mqttusername: str | None = None,
    mqttpassword: str | None = None,
    debug: int = 0,
) -> int:
    """Run BoneIO."""
    configure_logger(log_config=config.logger, debug=debug)
    web_server: WebServer | None = None
    tasks: set[asyncio.Task[None]] = set()
    loop = asyncio.get_event_loop()
    stack = AsyncExitStack()
    event_bus = await stack.enter_async_context(EventBus.create())
    shutdown_event = asyncio.Event()
    if debug >= 2:
        loop.set_debug(True)

    def signal_handler():
        """Handle shutdown signals."""
        _LOGGER.info("Received shutdown signal, initiating graceful shutdown...")
        shutdown_event.set()

    # Register signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    # Initialize message bus based on config
    if config.mqtt is not None:
        if mqttusername is not None:
            config.mqtt.username = mqttusername
        if mqttpassword is not None:
            config.mqtt.password = mqttpassword
        message_bus = MQTTClient(config=config.mqtt)
    else:
        message_bus = LocalMessageBus()

    gpio_manager = stack.enter_context(GpioManager.create())
    manager = Manager(
        config=config,
        message_bus=message_bus,
        event_bus=event_bus,
        config_file_path=config_file,
        gpio_manager=gpio_manager,
    )
    # Convert coroutines to Tasks
    message_bus.manager = manager
    tasks.update(manager.tasks)

    message_bus_type = "MQTT" if isinstance(message_bus, MQTTClient) else "Local"
    _LOGGER.info("Starting message bus %s.", message_bus_type)
    message_bus_task = asyncio.create_task(message_bus.start_client())
    tasks.add(message_bus_task)
    message_bus_task.add_done_callback(tasks.discard)

    # Start web server if configured
    if config.web is not None:
        _LOGGER.info("Starting Web server.")
        web_server = WebServer(
            config=config,
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
    except Exception as e:
        _LOGGER.error("Unexpected error: %s - %s", type(e).__name__, e)
    except BaseException as e:
        _LOGGER.error("Unexpected BaseException: %s - %s", type(e).__name__, e)
    finally:
        _LOGGER.info("Cleaning up resources...")

        # Trigger web server shutdown if it's running
        if web_server is not None:
            try:
                _LOGGER.info("Requesting web server shutdown...")
                await web_server.trigger_shutdown()
            except Exception as e:
                _LOGGER.error("Error triggering web server shutdown: %s", e)

        # Stop the event bus
        event_bus.request_stop()

        # Create a copy of tasks set to avoid modification during iteration
        if tasks:
            # Cancel and wait for all remaining tasks
            # Web server task will be cancelled here if it hasn't finished after trigger_shutdown
            for task in tasks:
                if not task.done():
                    _LOGGER.debug(
                        "Cancelling task: %s",
                        task.get_name() if hasattr(task, "get_name") else task,
                    )
                    task.cancel()

            # Wait for all tasks to complete
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                _LOGGER.error("Error during cleanup: %s - %s", type(e).__name__, e)

        _LOGGER.info("Shutdown complete")
    return 0
