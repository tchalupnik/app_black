"""
Provide an MQTT client for providing BoneIO MQTT broker.
Code based on cgarwood/python-openzwave-mqtt.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import aiomqtt
import anyio
import anyio.abc
from aiomqtt import MqttError, Will
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from paho.mqtt.properties import Properties

from boneio.config import MqttConfig
from boneio.events import EventBus
from boneio.message_bus.basic import (
    AutoDiscoveryMessage,
    AutoDiscoveryMessageType,
)

from . import MessageBus, ReceiveMessage

_LOGGER = logging.getLogger(__name__)


@dataclass
class StreamMessage:
    topic: str
    payload: str | None
    retain: bool = False


@dataclass
class MqttMessageBus(MessageBus):
    """Represent an MQTT client."""

    _tg: anyio.abc.TaskGroup
    client: aiomqtt.Client
    config: MqttConfig
    event_bus: EventBus
    _send_stream: MemoryObjectSendStream[StreamMessage]
    _receive_stream: MemoryObjectReceiveStream[StreamMessage]
    connection_established: bool = False
    _mqtt_energy_listeners: dict[str, Callable[[str], Coroutine[Any, Any, None]]] = (
        field(default_factory=dict)
    )
    _autodiscovery_messages: dict[
        AutoDiscoveryMessageType, list[AutoDiscoveryMessage]
    ] = field(default_factory=lambda: defaultdict(list))

    @classmethod
    @asynccontextmanager
    async def create(
        cls, config: MqttConfig, event_bus: EventBus
    ) -> AsyncGenerator[MqttMessageBus]:
        async with anyio.create_task_group() as tg:
            # it is done that way because aiomqtt doesn't propagate exceptions.
            async with _create_client(config) as client:
                send_stream, receive_stream = anyio.create_memory_object_stream[
                    StreamMessage
                ]()
                try:
                    this = cls(
                        _tg=tg,
                        client=client,
                        config=config,
                        event_bus=event_bus,
                        _send_stream=send_stream,
                        _receive_stream=receive_stream,
                    )
                    yield this
                finally:
                    _LOGGER.info("Cleaning up MQTT...")
                    tg.cancel_scope.cancel()

    async def subscribe(self, receive_message: ReceiveMessage) -> None:
        """Connect and subscribe to manager topics + host stats."""
        self._tg.start_soon(self._handle_publish)
        self._tg.start_soon(self._handle_messages, receive_message)

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
        await self.client.subscribe(topic=args)

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
        payload: str | None,
        retain: bool = False,
    ) -> None:
        """Send a message from the manager options."""
        self._tg.start_soon(
            lambda: self._send_stream.send(
                StreamMessage(topic=topic, payload=payload, retain=retain)
            )
        )

    def is_connection_established(self) -> bool:
        """State of MQTT Client."""
        return self.connection_established

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
            payload = message.payload
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode()
            elif isinstance(payload, (int, float)):
                payload = str(payload)

            if not isinstance(payload, str):
                _LOGGER.warning(
                    "Received message with unsupported payload type: %s",
                    type(payload),
                )
                continue

            is_already_handled = False
            if message.topic.matches(f"{self.config.ha_discovery.topic_prefix}/status"):
                if payload == "online":
                    for messages in self._autodiscovery_messages.values():
                        for msg in messages:
                            self.send_message(
                                topic=msg.topic,
                                payload=msg.payload.model_dump_json(),
                                retain=True,
                            )

                    self.event_bus.signal_ha_online()
                is_already_handled = True
            if message.topic.matches(f"{self.config.topic_prefix}/energy/#"):
                for topic, listener_callback in self._mqtt_energy_listeners.items():
                    if message.topic.matches(topic):
                        is_already_handled = True
                        await listener_callback(payload)
                        break
            if not is_already_handled:
                _LOGGER.debug(
                    "Received message topic: %s, payload: %s",
                    message.topic,
                    payload,
                )
                await receive_message(str(message.topic), payload)

    async def _handle_publish(self) -> None:
        """Publish messages as they are put on the stream."""
        async with self._receive_stream as receiver:
            async for message in receiver:
                await self._publish(
                    topic=message.topic, payload=message.payload, retain=message.retain
                )

    def add_autodiscovery_message(self, message: AutoDiscoveryMessage) -> None:
        if not self.config.ha_discovery.enabled:
            return
        _LOGGER.debug(
            "Sending HA discovery for %s: %s. Topic: %s",
            message.type.value,
            message.payload.name,
            message.topic,
        )
        self._autodiscovery_messages[message.type].append(message)
        self.send_message(
            topic=message.topic,
            payload=message.payload.model_dump_json(exclude_none=True),
            retain=True,
        )

    def clear_autodiscovery_messages_by_type(
        self, type: AutoDiscoveryMessageType
    ) -> None:
        self._autodiscovery_messages[type] = []


@asynccontextmanager
async def _create_client(config: MqttConfig) -> AsyncGenerator[aiomqtt.Client]:
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
                topic = f"{config.topic_prefix}/state"
                _LOGGER.info("Sending message topic: %s, payload online.", topic)
                await client.publish(topic, payload="online", retain=True)
                try:
                    yield client
                finally:
                    _LOGGER.info("Sending message topic: %s, payload: offline.", topic)
                    await client.publish(topic, payload="offline", retain=True)

        except MqttError as err:
            _LOGGER.error(
                "MQTT error: %s. Reconnecting in %s seconds",
                err,
                reconnect_interval,
            )
            await anyio.sleep(reconnect_interval)
            reconnect_interval = reconnect_interval * 2
