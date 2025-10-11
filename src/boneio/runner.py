"""Runner code for boneIO. Based on HA runner."""

from __future__ import annotations

import logging
import warnings
from contextlib import AbstractAsyncContextManager
from pathlib import Path

import anyio

from boneio.asyncio_ import handle_signals
from boneio.config import Config
from boneio.events import EventBus
from boneio.logger import configure_logger
from boneio.manager import Manager
from boneio.message_bus.local import LocalMessageBus
from boneio.message_bus.mqtt import MqttMessageBus
from boneio.webui.web_server import WebServer

# Filter out cryptography deprecation warning
warnings.filterwarnings("ignore", category=DeprecationWarning, module="cryptography")

_LOGGER = logging.getLogger(__name__)


async def start(
    config: Config,
    config_file_path: Path,
    mqttusername: str | None = None,
    mqttpassword: str | None = None,
    debug: int = 0,
    dry: bool = False,
) -> None:
    """Run BoneIO."""
    async with anyio.create_task_group() as tg:
        tg.start_soon(handle_signals, "Signal received")

        configure_logger(log_config=config.logger, debug=debug)
        async with EventBus.create() as event_bus:
            # Initialize message bus based on config
            if config.mqtt is not None:
                if mqttusername is not None:
                    config.mqtt.username = mqttusername
                if mqttpassword is not None:
                    config.mqtt.password = mqttpassword

                def create_message_bus() -> AbstractAsyncContextManager[MqttMessageBus]:
                    assert config.mqtt is not None
                    return MqttMessageBus.create(config.mqtt)

                create_message_bus_fun = create_message_bus
            else:

                def create_message_bus() -> AbstractAsyncContextManager[
                    LocalMessageBus
                ]:
                    return LocalMessageBus.create()

                create_message_bus_fun = create_message_bus
            async with create_message_bus_fun() as message_bus:
                async with Manager.create(
                    config=config,
                    message_bus=message_bus,
                    event_bus=event_bus,
                    config_file_path=config_file_path,
                    dry=dry,
                ) as manager:
                    await message_bus.subscribe(manager.receive_message)

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

                    await anyio.sleep_forever()
