"""Group output module."""

from __future__ import annotations

import asyncio

from boneio.config import OutputGroupConfig
from boneio.const import COVER, OFF, ON, SWITCH
from boneio.helper.events import EventBus
from boneio.helper.state_manager import StateManager
from boneio.message_bus.basic import MessageBus
from boneio.models import OutputState
from boneio.relay.basic import BasicRelay


class OutputGroup(BasicRelay):
    """Cover class of boneIO"""

    def __init__(
        self,
        config: OutputGroupConfig,
        message_bus: MessageBus,
        state_manager: StateManager,
        topic_prefix: str,
        relay_id: str,
        event_bus: EventBus,
        members: list[BasicRelay],
    ) -> None:
        """Initialize cover class."""
        self._loop = asyncio.get_event_loop()
        super().__init__(
            config=config,
            message_bus=message_bus,
            state_manager=state_manager,
            topic_prefix=topic_prefix,
            relay_id=relay_id,
            event_bus=event_bus,
            members=members,
            output_type=SWITCH,
            restored_state=False,
            topic_type="group",
        )
        self._group_members = [x for x in members if x.output_type != COVER]
        self._timer_handle = None
        self.check_state()

        for member in self._group_members:
            self._event_bus.add_event_listener(
                event_type="output",
                entity_id=member.id,
                listener_id=self.id,
                target=self.event_listener,
            )

    def check_state(self) -> None:
        for x in self._group_members:
            if x.state == ON:
                self._state = ON
                return

    async def event_listener(self, event: OutputState = None) -> None:
        """Listen for events called by children relays."""
        state = ON if any(x.state == ON for x in self._group_members) else OFF
        if state != self._state or not event:
            self._state = state
            self._loop.create_task(self.async_send_state())

    async def async_turn_on(self) -> None:
        """Call turn on action."""
        for x in self._group_members:
            self._loop.create_task(x.async_turn_on())

    async def async_turn_off(self) -> None:
        """Call turn off action."""
        for x in self._group_members:
            self._loop.create_task(x.async_turn_off())

    @property
    def is_active(self) -> bool:
        """Is relay active."""
        return self._state == ON

    async def async_send_state(self) -> None:
        """Send state to Mqtt on action."""
        self.message_bus.send_message(
            topic=self._send_topic, payload=self.payload(), retain=True
        )
