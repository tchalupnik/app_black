"""
Provide an MQTT client for providing BoneIO MQTT broker.
Code based on cgarwood/python-openzwave-mqtt.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import aiomqtt
import anyio
import anyio.abc
from aiomqtt import MqttError, Will
from anyio import TASK_STATUS_IGNORED
from anyio.abc import TaskStatus
from paho.mqtt.properties import Properties

from boneio.config import MqttConfig
from boneio.events import EventBus
from boneio.helper.queue import UniqueQueue
from boneio.message_bus.basic import (
    MqttAutoDiscoveryMessage,
    MqttAutoDiscoveryMessageType,
)

from . import MessageBus, ReceiveMessage

_LOGGER = logging.getLogger(__name__)


@dataclass
class MqttMessageBus(MessageBus):
    """Represent an MQTT client."""

    _tg: anyio.abc.TaskGroup
    client: aiomqtt.Client
    config: MqttConfig
    event_bus: EventBus
    connection_established: bool = False
    publish_queue: UniqueQueue = field(default_factory=UniqueQueue)
    _mqtt_energy_listeners: dict[
        str, Callable[[str, str], Coroutine[Any, Any, None]]
    ] = field(default_factory=dict)
    _autodiscovery_messages: dict[
        MqttAutoDiscoveryMessageType, list[MqttAutoDiscoveryMessage]
    ]

    @classmethod
    @asynccontextmanager
    async def create(
        cls, config: MqttConfig, event_bus: EventBus
    ) -> AsyncGenerator[MqttMessageBus]:
        async with anyio.create_task_group() as tg:
            # it is done that way because aiomqtt doesn't propagate exceptions.
            client = await tg.start(cls._create_client, config)
            try:
                this = cls(tg, client, config, event_bus)
                yield this
            finally:
                _LOGGER.info("Cleaning up MQTT...")
                tg.cancel_scope.cancel()

    @classmethod
    async def _create_client(
        cls,
        config: MqttConfig,
        task_status: TaskStatus[aiomqtt.Client] = TASK_STATUS_IGNORED,
    ) -> None:
        reconnect_interval: int = 1
        while True:
            try:
                async with aiomqtt.Client(
                    config.host,
                    config.port,
                    username=config.username,
                    password=config.password,
                    will=Will(topic=f"{config.topic_prefix}/state", payload="offline"),
                    clean_session=True,
                ) as client:
                    # yield this
                    task_status.started(client)
                    try:
                        await anyio.sleep_forever()
                    finally:
                        topic = f"{config.topic_prefix}/state"
                        _LOGGER.info(
                            "Sending message topic: %s, payload: offline", topic
                        )
                        await client.publish(topic, payload="offline", retain=True)

            except MqttError as err:
                _LOGGER.error(
                    "MQTT error: %s. Reconnecting in %s seconds",
                    err,
                    reconnect_interval,
                )
                await anyio.sleep(reconnect_interval)
                reconnect_interval = reconnect_interval * 2

    async def subscribe(self, receive_messages: ReceiveMessage) -> None:
        """Connect and subscribe to manager topics + host stats."""
        self.publish_queue.set_connected(True)

        self._tg.start_soon(self._handle_publish)
        self._tg.start_soon(self._handle_messages, receive_messages)

        if not self.connection_established:
            self.connection_established = True
            _LOGGER.info("Sending online state.")
            topic = f"{self.config.topic_prefix}/state"
            self.send_message(topic=topic, payload="online", retain=True)

        topics = (
            [
                f"{self.config.topic_prefix}/cmd/+/+/#",
                "homeassistant/status",
            ]
            + list(self._mqtt_energy_listeners.keys())
            + [k.value.lower() for k in self._autodiscovery_messages.keys()]
        )

        args = [(topic, 0) for topic in topics]
        # e.g. subscribe([("my/topic", SubscribeOptions(qos=0), ("another/topic", SubscribeOptions(qos=2)])
        _LOGGER.debug("Subscribing to %s", args)
        await self.client.subscribe(topic=args, qos=0)

    async def subscribe_and_listen(
        self, topic: str, callback: Callable[[str], Coroutine[Any, Any, None]]
    ) -> None:
        await self.client.subscribe(topic=topic)
        # TODO: why does it especially say energy listener here?
        self._mqtt_energy_listeners[topic] = callback

    async def unsubscribe_and_stop_listen(self, topic: str) -> None:
        await self.client.unsubscribe(topic=topic, timeout=10.0)
        del self._mqtt_energy_listeners[topic]

    def send_message(
        self,
        topic: str,
        payload: str | int | dict | None,
        retain: bool = False,
    ) -> None:
        """Send a message from the manager options."""
        to_publish = (
            topic,
            json.dumps(payload) if isinstance(payload, dict) else payload,
            retain,
        )
        self.publish_queue.put_nowait(to_publish)

    def is_connection_established(self) -> bool:
        """State of MQTT Client."""
        return self.connection_established

    async def announce_offline(self) -> None:
        """Announce that the device is offline."""
        await self._publish(
            topic=f"{self.config.topic_prefix}/state",
            payload="offline",
            retain=True,
        )

    async def _publish(
        self,
        topic: str,
        payload: str | None = None,
        retain: bool = False,
        properties: Properties | None = None,
        timeout: float = 10.0,
    ) -> None:
        _LOGGER.debug("Sending message topic: %s, payload: %s", topic, payload)
        await self.client.publish(
            topic,
            payload=payload,
            properties=properties,
            retain=retain,
            timeout=timeout,
        )

    async def _handle_messages(self, receive_message: ReceiveMessage) -> None:
        """Handle messages with callback or remove obsolete HA discovery messages."""

        async for message in self.client.messages:
            payload = message.payload.decode()
            callback_start = True
            if message.topic.matches(f"{self.config.ha_discovery.topic_prefix}/status"):
                if message == "online":
                    for messages in self._autodiscovery_messages.values():
                        for msg in messages:
                            self.send_message(
                                topic=msg.topic,
                                payload=msg.payload.model_dump(),
                                retain=True,
                            )

                    self.event_bus.signal_ha_online()
                callback_start = False
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
                await receive_message(str(message.topic), payload)

    async def _handle_publish(self) -> None:
        """Publish messages as they are put on the queue."""
        while True:
            to_publish: tuple[
                str, str | int | None, bool
            ] = await self.publish_queue.get()
            await self._publish(*to_publish)
            self.publish_queue.task_done()

    def add_autodiscovery_message(self, message: MqttAutoDiscoveryMessage) -> None:
        if not self.config.ha_discovery.enabled:
            return
        _LOGGER.debug(
            "Sending HA discovery for %s entity, %s.",
            message.type,
            message.payload.name,
        )
        self._autodiscovery_messages[message.type].append(message)
        self.send_message(
            topic=message.topic, payload=message.payload.model_dump(), retain=True
        )

    def clear_autodiscovery_messages_by_type(
        self, type: MqttAutoDiscoveryMessageType
    ) -> None:
        self._autodiscovery_messages[type] = []
