from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import anyio
import anyio.abc
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from . import MessageBus, ReceiveMessage

_LOGGER = logging.getLogger(__name__)


@dataclass
class LocalMessageBus(MessageBus):
    """Local message bus that doesn't use MQTT."""

    tg: anyio.abc.TaskGroup
    send_stream: MemoryObjectSendStream[tuple[str, str | None]]
    receive_stream: MemoryObjectReceiveStream[tuple[str, str | None]]
    connection_established: bool = True

    def send_message(
        self, topic: str, payload: str | None, retain: bool = False
    ) -> None:
        """Route message locally."""
        self.tg.start_soon(self.send_stream.send, (topic, payload))

    async def subscribe(self, receive_message: ReceiveMessage) -> None:
        """Subscribe to a topic."""

        async def _message_processor() -> None:
            async for topic, payload in self.receive_stream:
                _LOGGER.debug("Received message on topic %s: %s", topic, payload)
                if not topic.startswith("boneio/boneio"):
                    continue
                if payload is not None:
                    await receive_message(topic, payload)

        self.tg.start_soon(_message_processor)

    @classmethod
    @asynccontextmanager
    async def create(cls) -> AsyncGenerator[LocalMessageBus]:
        _LOGGER.info("Starting LOCAL message bus!")
        async with anyio.create_task_group() as tg:
            send_stream, receive_stream = anyio.create_memory_object_stream[
                tuple[str, str | None]
            ]()
            this = cls(tg, send_stream, receive_stream)
            _LOGGER.info("Sending online state.")
            this.send_message(topic="boneio/state", payload="online", retain=True)
            try:
                yield this
            finally:
                tg.cancel_scope.cancel()

    async def announce_offline(self) -> None:
        """Announce that the device is offline."""
        _LOGGER.info("Sending offline state.")
        self.send_message(topic="boneio/state", payload="offline", retain=True)

    def is_connection_established(self) -> bool:
        return self.connection_established

    async def subscribe_and_listen(
        self, topic: str, callback: Callable[[str], Coroutine[Any, Any, None]]
    ) -> None:
        """Subscribe to a topic and listen for messages."""

    async def unsubscribe_and_stop_listen(self, topic: str) -> None:
        """Unsubscribe from a topic and stop listening."""
