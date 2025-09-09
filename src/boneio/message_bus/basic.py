"""Message bus abstraction for BoneIO."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boneio.manager import Manager


class MessageBus(ABC):
    """Base class for message handling."""

    @abstractmethod
    async def send_message(
        self, topic: str, payload: str | dict, retain: bool = False
    ) -> None:
        """Send a message."""

    @property
    @abstractmethod
    def state(self) -> bool:
        """Get bus state."""

    @abstractmethod
    async def start_client(self) -> None:
        """Start the message bus client."""

    @abstractmethod
    def set_manager(self, manager: Manager) -> None:
        """Set manager."""

    @abstractmethod
    async def announce_offline(self) -> None:
        """Announce that the device is offline."""

    @abstractmethod
    async def subscribe_and_listen(
        self, topic: str, callback: Callable[[str, str], Awaitable[None]]
    ) -> None:
        """Subscribe to a topic and listen for messages."""

    @abstractmethod
    async def unsubscribe_and_stop_listen(self, topic: str) -> None:
        """Unsubscribe from a topic and stop listening."""
