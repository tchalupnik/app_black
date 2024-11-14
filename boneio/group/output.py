"""Group output module."""

from __future__ import annotations
import asyncio
from typing import List
from boneio.const import COVER, SWITCH, ON, OFF
from boneio.relay.basic import BasicRelay


class OutputGroup(BasicRelay):
    """Cover class of boneIO"""

    def __init__(
        self,
        members: List[BasicRelay],
        output_type: str = SWITCH,
        restored_state: bool = False,
        all_on_behaviour: bool = False,
        **kwargs,
    ) -> None:
        """Initialize cover class."""
        self._loop = asyncio.get_event_loop()
        super().__init__(
            **kwargs,
            output_type=output_type,
            restored_state=False,
            topic_type="group",
        )
        self._all_on_behaviour = all_on_behaviour
        self._group_members = [x for x in members if x.output_type != COVER]
        self._timer_handle = None
        self.check_state()

        for member in self._group_members:
            self._event_bus.add_output_listener(
                output_id=member.id,
                group_id=self.id,
                target=self.event_listener,
            )

    def check_state(self) -> None:
        for x in self._group_members:
            if x.state == ON:
                self._state = ON
                return

    async def event_listener(self, relay_id=None) -> None:
        """Listen for events called by children relays."""
        if self._all_on_behaviour:
            state = (
                ON if all(x.state == ON for x in self._group_members) else OFF
            )
        else:
            state = (
                ON if any(x.state == ON for x in self._group_members) else OFF
            )
        if state != self._state or not relay_id:
            self._state = state
            self._loop.call_soon_threadsafe(self.send_state)

    async def async_turn_on(self) -> None:
        """Call turn on action."""
        await asyncio.gather(
            *[
                self._loop.run_in_executor(self.executor, x.turn_on)
                for x in self._group_members
            ]
        )

    async def async_turn_off(self) -> None:
        """Call turn off action."""
        await asyncio.gather(
            *[
                self._loop.run_in_executor(self.executor, x.turn_off)
                for x in self._group_members
            ]
        )

    @property
    def is_active(self) -> bool:
        """Is relay active."""
        return self._state == ON

    def send_state(self) -> None:
        """Send state to Mqtt on action."""
        self._send_message(
            topic=self._send_topic, payload=self.payload(), retain=True
        )
