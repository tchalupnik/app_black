"""
Provide an MQTT client for providing BoneIO MQTT broker.
Code based on cgarwood/python-openzwave-mqtt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Any

import anyio
import anyio.abc
import paho.mqtt.client as mqtt
from aiomqtt import Client as AsyncioClient
from aiomqtt import Message, MqttError, Will
from paho.mqtt.properties import Properties
from paho.mqtt.subscribeoptions import SubscribeOptions

from boneio.config import MqttConfig
from boneio.const import (
    OFFLINE,
    ONLINE,
    PAHO,
    STATE,
)
from boneio.helper.queue import UniqueQueue
from boneio.message_bus import MessageBus

if TYPE_CHECKING:
    from boneio.manager import Manager

_LOGGER = logging.getLogger(__name__)


class MQTTClient(MessageBus):
    """Represent an MQTT client."""

    def __init__(self, config: MqttConfig, tg: anyio.abc.TaskGroup) -> None:
        """Set up client."""
        _LOGGER.info("Starting MQTT message bus!")
        self._tg = tg
        self.manager: Manager | None = None
        self.config = config
        self.asyncio_client: AsyncioClient = None
        self.create_client()
        self.reconnect_interval = 1
        self._connection_established = False
        self.publish_queue: UniqueQueue = UniqueQueue()
        self._mqtt_energy_listeners: dict[
            str, Callable[[str, str], Coroutine[Any, Any, None]]
        ] = {}
        self._discovery_topics = (
            [
                f"{self.config.ha_discovery.topic_prefix}/{ha_type}/{self.config.topic_prefix}/#"
                for ha_type in self.config.autodiscovery_messages
            ]
            if self.config.ha_discovery.enabled
            else []
        )
        self._topics = [
            self.config.subscribe_topic(),
            "homeassistant/status",
        ]
        self._running = True
        self._cancel_future: asyncio.Future | None = None

    def create_client(self) -> None:
        """Create the asyncio client."""
        _LOGGER.debug("Creating client %s:%s", self.config.host, self.config.port)
        self.asyncio_client = AsyncioClient(
            self.config.host,
            self.config.port,
            username=self.config.username,
            password=self.config.password,
            will=Will(
                topic=f"{self.config.topic_prefix}/{STATE}",
                payload=OFFLINE,
                qos=0,
                retain=False,
            ),
            client_id=mqtt.base62(uuid.uuid4().int, padding=22),
            logger=logging.getLogger(PAHO),
            clean_session=True,
        )

    async def publish(
        self,
        topic: str,
        payload: str | None = None,
        retain: bool = False,
        qos: int = 0,
        properties: Properties | None = None,
        timeout: float = 10,
    ) -> None:
        """Publish to topic.

        Can raise asyncio_mqtt.MqttError.
        """
        params: dict = {"qos": qos, "retain": retain, "timeout": timeout}
        if payload:
            params["payload"] = payload
        if properties:
            params["properties"] = properties

        _LOGGER.debug("Sending message topic: %s, payload: %s", topic, payload)
        await self.asyncio_client.publish(topic, **params)

    async def subscribe(
        self,
        topics: list[str],
        qos: int = 0,
        options: SubscribeOptions | None = None,
        properties: Properties | None = None,
        timeout: float = 10.0,
    ) -> None:
        """Subscribe to topic.

        Can raise asyncio_mqtt.MqttError.
        """
        args = []
        for topic in topics:
            args.append((topic, qos))
        params: dict = {"qos": qos}
        if options:
            params["options"] = options
        if properties:
            params["properties"] = properties

        # e.g. subscribe([("my/topic", SubscribeOptions(qos=0), ("another/topic", SubscribeOptions(qos=2)])
        _LOGGER.debug("Subscribing to %s", args)
        await self.asyncio_client.subscribe(topic=args, **params, timeout=timeout)

    async def subscribe_and_listen(
        self, topic: str, callback: Callable[[str], Coroutine[Any, Any, None]]
    ) -> None:
        self._mqtt_energy_listeners[topic] = callback

    async def unsubscribe_and_stop_listen(self, topic: str) -> None:
        await self.unsubscribe([topic])
        del self._mqtt_energy_listeners[topic]

    async def unsubscribe(
        self,
        topics: list[str],
        properties: Properties | None = None,
        timeout: float = 10.0,
    ) -> None:
        """Unsubscribe from topic.

        Can raise asyncio_mqtt.MqttError.
        """
        params: dict = {"timeout": timeout}
        if properties:
            params["properties"] = properties

        await self.asyncio_client.unsubscribe(topic=topics, **params)

    def send_message(
        self,
        topic: str,
        payload: str | int | dict | None,
        retain: bool = False,
    ) -> None:
        """Send a message from the manager options."""
        to_publish = (
            topic,
            json.dumps(payload) if type(payload) is dict else payload,
            retain,
        )
        self.publish_queue.put_nowait(to_publish)

    async def _handle_publish(self) -> None:
        """Publish messages as they are put on the queue."""
        while True:
            to_publish: tuple = await self.publish_queue.get()
            await self.publish(*to_publish)
            self.publish_queue.task_done()

    async def announce_offline(self) -> None:
        """Announce that the device is offline."""
        await self.publish(
            topic=f"{self.config.topic_prefix}/{STATE}",
            payload=OFFLINE,
            retain=True,
        )

    @classmethod
    @asynccontextmanager
    async def create(cls, config: MqttConfig) -> AsyncGenerator[MQTTClient]:
        """Keep the event loop alive and process any periodic tasks."""
        async with anyio.create_task_group() as tg:
            this = cls(config, tg)

            async def run() -> None:
                try:
                    while True:
                        try:
                            await this._subscribe_manager()
                        except MqttError as err:
                            this.reconnect_interval = min(
                                this.reconnect_interval * 2, 60
                            )
                            _LOGGER.error(
                                "MQTT error: %s. Reconnecting in %s seconds",
                                err,
                                this.reconnect_interval,
                            )
                            this._connection_established = False
                            this.publish_queue.set_connected(False)
                            await asyncio.sleep(this.reconnect_interval)
                            this.create_client()  # reset connect/reconnect futures
                except asyncio.CancelledError:
                    _LOGGER.info("MQTT client shutting down...")
                    await this.asyncio_client.disconnect(timeout=1.0)
                    raise

            tg.start_soon(run)
            yield this

    async def _subscribe_manager(self) -> None:
        """Connect and subscribe to manager topics + host stats."""
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(self.asyncio_client)
            tg = await stack.enter_async_context(anyio.create_task_group())
            self.publish_queue.set_connected(True)
            # Create a new future for this run
            self._cancel_future = asyncio.Future()

            async def wait_for_cancel():
                await self._cancel_future
                # When future completes, raise CancelledError to stop other tasks
                raise asyncio.CancelledError("Stop requested")

            tg.start_soon(self._handle_publish)

            # Messages that doesn't match a filter will get logged and handled here.
            messages = await stack.enter_async_context(self.asyncio_client.messages())

            tg.start_soon(lambda: self.handle_messages(messages))
            if not self._connection_established:
                self._connection_established = True
                _LOGGER.info("Sending online state.")
                topic = f"{self.config.topic_prefix}/{STATE}"
                self.send_message(topic=topic, payload=ONLINE, retain=True)

            # Add cancel_future to tasks
            tg.start_soon(wait_for_cancel)

            topics = (
                self._topics
                + list(self._mqtt_energy_listeners.keys())
                + self._discovery_topics
            )
            await self.subscribe(topics=topics)

    def is_connection_established(self) -> bool:
        """State of MQTT Client."""
        return self._connection_established

    async def handle_messages(self, messages: AsyncGenerator[Message, None]) -> None:
        """Handle messages with callback or remove obsolete HA discovery messages."""
        async for message in messages:
            payload = message.payload.decode()
            callback_start = True
            for discovery_topic in self._discovery_topics:
                if message.topic.matches(discovery_topic):
                    callback_start = False
                    topic = str(message.topic)
                    if message.payload and not self.config.is_topic_in_autodiscovery(
                        topic
                    ):
                        _LOGGER.info("Removing unused discovery entity %s", topic)
                        self.send_message(topic=topic, payload=None, retain=True)
                    break
            if message.topic.matches(f"{self.config.topic_prefix}/energy/#"):
                for topic, listener_callback in self._mqtt_energy_listeners.items():
                    if message.topic.matches(topic):
                        callback_start = False
                        await listener_callback(payload)
                        break
            if callback_start:
                _LOGGER.debug(
                    "Received message topic: %s, payload: %s",
                    message.topic,
                    payload,
                )
                await self.manager.receive_message(str(message.topic), payload)
