"""Basic Relay module."""
from __future__ import annotations

import asyncio
import logging
import time

from boneio.const import COVER, LIGHT, NONE, OFF, ON, RELAY, STATE, SWITCH
from boneio.helper import BasicMqtt
from boneio.helper.events import EventBus, async_track_point_in_time, utcnow
from boneio.helper.util import callback
from boneio.models import OutputState

_LOGGER = logging.getLogger(__name__)


class BasicRelay(BasicMqtt):
    """Basic relay class."""

    def __init__(
        self,
        # callback: Callable[[OutputState], Awaitable[None]],
        id: str,
        event_bus: EventBus,
        name: str | None = None,
        output_type=SWITCH,
        restored_state: bool = False,
        topic_type: str = RELAY,
        **kwargs,
    ) -> None:
        """Initialize Basic relay."""
        self._momentary_turn_on = kwargs.pop("momentary_turn_on", None)
        self._momentary_turn_off = kwargs.pop("momentary_turn_off", None)
        super().__init__(id=id, name=name or id, topic_type=topic_type, **kwargs)
        self._output_type = output_type
        self._event_bus = event_bus
        if output_type == COVER:
            self._momentary_turn_on = None
            self._momentary_turn_off = None
        self._state = ON if restored_state else OFF
        # self._callback = callback
        self._momentary_action = None
        self._last_timestamp = 0.0
        self._loop = asyncio.get_running_loop()

    @property
    def is_mcp_type(self) -> bool:
        """Check if relay is mcp type."""
        return False

    @property
    def output_type(self) -> str:
        """HA type."""
        return self._output_type

    @property
    def is_light(self) -> bool:
        """Check if HA type is light"""
        return self._output_type == LIGHT

    @property
    def id(self) -> str:
        """Id of the relay.
        Has to be trimmed out of spaces because of MQTT handling in HA."""
        return self._id or self._pin_id

    @property
    def name(self) -> str:
        """Not trimmed id."""
        return self._name or self._pin_id

    @property
    def state(self) -> str:
        """Is relay active."""
        return self._state

    @property
    def last_timestamp(self) -> float:
        return self._last_timestamp

    def payload(self) -> dict:
        return {STATE: self.state}

    async def async_send_state(self, optimized_value: str | None = None) -> None:
        """Send state to Mqtt on action asynchronously."""
        if optimized_value:
            state = optimized_value
        else:
            state = ON if self.is_active else OFF
        self._state = state
        if self.output_type not in (COVER, NONE):
            self._send_message(
                topic=self._send_topic,
                payload={STATE: state},
                retain=True,
            )
        self._last_timestamp = time.time()
        event = OutputState(
            id=self.id,
            name=self.name,
            state=state,
            type=self.output_type,
            pin=self.pin_id,
            timestamp=self.last_timestamp,
            expander_id=self.expander_id,
        )
        await self._event_bus.async_trigger_output_event(output_id=self.id, event=event)
        await self._event_bus.async_trigger_event(event_type="output", entity_id=self.id, event=event)

    async def async_turn_on(self) -> None:
        self.turn_on()
        asyncio.create_task(self.async_send_state())

    async def async_turn_off(self) -> None:
        """Turn off the relay asynchronously."""
        self.turn_off()
        asyncio.create_task(self.async_send_state())

    async def async_toggle(self) -> None:
        """Toggle relay."""
        _LOGGER.debug("Toggle relay %s.", self.name)
        if self.is_active:
            await self.async_turn_off()
        else:
            await self.async_turn_on()

    def turn_on(self, time=None) -> None:
        """Call turn on action."""
        raise NotImplementedError
    
    def turn_off(self, time=None) -> None:
        """Call turn off action."""
        raise NotImplementedError

    def _execute_momentary_turn(self, momentary_type: str) -> None:
        """Execute momentary action."""
        if self._momentary_action:
            _LOGGER.debug("Cancelling momentary action for %s", self.name)
            self._momentary_action()
        (action, delayed_action) = (
            (self.turn_off, self._momentary_turn_on)
            if momentary_type == ON
            else (self.turn_on, self._momentary_turn_off)
        )
        if delayed_action:
            _LOGGER.debug("Applying momentary action for %s in %s", self.name, delayed_action.as_timedelta)
            self._momentary_action = async_track_point_in_time(
                loop=self._loop,
                action=lambda x: self._momentary_callback(time=x, action=action),
                point_in_time=utcnow() + delayed_action.as_timedelta,
            )

    @callback
    def _momentary_callback(self, time, action):
        _LOGGER.info("Momentary callback at %s for output %s", time, self.name)
        action(time=time)

    @property
    def is_active(self) -> bool:
        """Is active check."""
        raise NotImplementedError

    @property
    def expander_id(self) -> str:
        """Retrieve parent Expander ID."""
        return self._expander_id
