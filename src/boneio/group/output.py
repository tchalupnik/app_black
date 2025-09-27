"""Group output module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from boneio.config import OutputGroupConfig
from boneio.const import COVER
from boneio.events import EventBus, EventType
from boneio.helper.state_manager import StateManager
from boneio.helper.util import strip_accents
from boneio.message_bus.basic import MessageBus
from boneio.models import OutputState
from boneio.relay.basic import BasicRelay


@dataclass
class OutputGroup:
    """Cover class of boneIO"""

    config: OutputGroupConfig
    state_manager: StateManager
    event_bus: EventBus
    message_bus: MessageBus
    members: list[BasicRelay]
    topic_prefix: str
    output_type: str = "switch"
    state: Literal["ON", "OFF"] = "OFF"

    def __post_init__(self) -> None:
        """Initialize cover class."""
        self._group_members = [x for x in self.members if x.output_type != COVER]

        for member in self._group_members:
            self.event_bus.add_event_listener(
                event_type=EventType.OUTPUT,
                entity_id=member.id,
                listener_id=self.config.id,
                target=self.event_listener,
            )

    async def event_listener(self, event: OutputState = None) -> None:
        """Listen for events called by children relays."""
        state = "ON" if any(x.state == "ON" for x in self._group_members) else "OFF"
        if state != self.state or not event:
            self.state = state
            self.send_state()

    def turn_on(self) -> None:
        """Call turn on action."""
        self.state = "ON"
        for x in self._group_members:
            x.turn_on()

    def turn_off(self) -> None:
        """Call turn off action."""
        self.state = "OFF"
        for x in self._group_members:
            x.turn_off()

    def toggle(self) -> None:
        """Call toggle action."""
        if self.state == "ON":
            self.turn_off()
        else:
            self.turn_on()

    def is_active(self) -> bool:
        """Is relay active."""
        return self.state == "ON"

    def send_state(self) -> None:
        """Send state to Mqtt on action."""
        self.message_bus.send_message(
            topic=f"{self.topic_prefix}/relay/{strip_accents(self.id)}",
            payload={"state": self.state},
            retain=True,
        )
