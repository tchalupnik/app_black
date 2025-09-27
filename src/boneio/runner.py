"""Runner code for boneIO. Based on HA runner."""

from __future__ import annotations

import asyncio
import logging
import warnings
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import anyio
import hypercorn

from boneio.config import Config
from boneio.events import EventBus
from boneio.logger import configure_logger
from boneio.manager import Manager
from boneio.message_bus import LocalMessageBus, MQTTClient
from boneio.webui.web_server import WebServer

# Filter out cryptography deprecation warning
warnings.filterwarnings("ignore", category=DeprecationWarning, module="cryptography")

_LOGGER = logging.getLogger(__name__)


def asyncio_loop_exception_handler(
    loop: asyncio.AbstractEventLoop, context: dict[str, Any]
) -> None:
    exception = context.get("exception")
    if isinstance(exception, hypercorn.utils.LifespanFailureError):
        pass
    else:
        loop.default_exception_handler(context)


async def async_run(
    config: Config,
    config_file_path: Path,
    mqttusername: str | None = None,
    mqttpassword: str | None = None,
    debug: int = 0,
    dry: bool = False,
) -> int:
    asyncio.get_event_loop().set_exception_handler(asyncio_loop_exception_handler)
    """Run BoneIO."""
    configure_logger(log_config=config.logger, debug=debug)
    stack = AsyncExitStack()
    event_bus = await stack.enter_async_context(EventBus.create())
    # Initialize message bus based on config
    if config.mqtt is not None:
        if mqttusername is not None:
            config.mqtt.username = mqttusername
        if mqttpassword is not None:
            config.mqtt.password = mqttpassword
        message_bus = await stack.enter_async_context(MQTTClient.create(config.mqtt))
    else:
        message_bus = await stack.enter_async_context(LocalMessageBus.create())

    manager = await stack.enter_async_context(
        Manager.create(
            config=config,
            message_bus=message_bus,
            event_bus=event_bus,
            config_file_path=config_file_path,
            dry=dry,
        )
    )
    message_bus.manager = manager

    # Start web server if configured
    if config.web is not None:
        _LOGGER.info("Starting Web server.")
        web_server = WebServer(
            config=config,
            config_file_path=config_file_path,
            manager=manager,
        )
        await web_server.start_webserver()
    else:
        _LOGGER.info("Web server not configured.")

    try:
        await anyio.sleep_forever()
    finally:
        _LOGGER.info("Cleaning up resources...")
        await message_bus.announce_offline()
        _LOGGER.info("Shutdown complete")
    return 0
