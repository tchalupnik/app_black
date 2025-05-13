"""Message bus abstraction for BoneIO."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Awaitable, Callable, Union

if TYPE_CHECKING:
    from boneio.manager import Manager

_LOGGER = logging.getLogger(__name__)

class MessageBus(ABC):
    """Base class for message handling."""
    
    @abstractmethod
    async def send_message(self, topic: str, payload: Union[str, dict], retain: bool = False) -> None:
        """Send a message."""
        pass

    @property
    @abstractmethod
    def state(self) -> bool:
        """Get bus state."""
        pass
        
    @abstractmethod
    async def start_client(self) -> None:
        """Start the message bus client."""
        pass

    @abstractmethod
    def set_manager(self, manager: Manager) -> None:
        """Set manager."""
        pass

    @abstractmethod
    async def announce_offline(self) -> None:
        """Announce that the device is offline."""
        pass

    @abstractmethod
    async def subscribe_and_listen(self, topic: str, callback: Callable[[str, str], Awaitable[None]]) -> None:
        """Subscribe to a topic and listen for messages."""
        pass

    @abstractmethod
    async def unsubscribe_and_stop_listen(self, topic: str) -> None:
        """Unsubscribe from a topic and stop listening."""
        pass

