from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boneio.manager import Manager

from boneio.message_bus import MessageBus

_LOGGER = logging.getLogger(__name__)


class LocalMessageBus(MessageBus):
    """Local message bus that doesn't use MQTT."""

    def __init__(self):
        """Initialize local message bus."""
        self.connection_established = True
        self._subscribers: dict[str, set[Callable]] = {}
        self._retain_values: dict[str, str | dict] = {}
        self.manager: Manager | None = None

    async def send_message(
        self, topic: str, payload: str | dict, retain: bool = False
    ) -> None:
        """Route message locally."""
        if retain:
            self._retain_values[topic] = payload

        if topic in self._subscribers:
            for callback in self._subscribers[topic]:
                try:
                    await callback(topic, payload)
                except Exception as e:
                    _LOGGER.error("Error in local message callback: %s", e)

    async def subscribe(self, topic: str, callback: Callable) -> None:
        """Subscribe to a topic."""
        if topic not in self._subscribers:
            self._subscribers[topic] = set()
        self._subscribers[topic].add(callback)

        # Send retained value if exists
        if topic in self._retain_values:
            asyncio.create_task(callback(topic, self._retain_values[topic]))

    async def start_client(self) -> None:
        """Keep the event loop alive and process any periodic tasks."""
        while True:
            if self.manager is not None:
                await self.manager.reconnect_callback()
            await asyncio.sleep(60)  # Run reconnect callback every minute like MQTT

    async def announce_offline(self) -> None:
        """Announce that the device is offline."""

    def is_connection_established(self) -> bool:
        return self.connection_established
