"""Basic Relay module."""
from __future__ import annotations

import asyncio
import logging
import time

from boneio.const import COVER, LIGHT, NONE, OFF, ON, RELAY, STATE, SWITCH
from boneio.helper import BasicMqtt
from boneio.helper.events import EventBus, async_track_point_in_time, utcnow
from boneio.helper.interlock import SoftwareInterlockManager
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
        topic_prefix: str,
        name: str | None = None,
        output_type=SWITCH,
        restored_state: bool = False,
        topic_type: str = RELAY,
        interlock_manager: SoftwareInterlockManager | None = None,
        interlock_groups: list[str] = [],
        **kwargs,
    ) -> None:
        """Initialize Basic relay.
        Supports virtual_power_usage for energy monitoring.
        """
        self._momentary_turn_on = kwargs.pop("momentary_turn_on", None)
        self._momentary_turn_off = kwargs.pop("momentary_turn_off", None)
        self.virtual_power_usage = kwargs.pop("virtual_power_usage", None)
        if self.virtual_power_usage is not None:
            try:
                # Accept '9W' or '9' (as int/float)
                if isinstance(self.virtual_power_usage, str) and self.virtual_power_usage.lower().endswith('w'):
                    self.virtual_power_usage = float(self.virtual_power_usage[:-1])
                else:
                    self.virtual_power_usage = float(self.virtual_power_usage)
            except Exception as e:
                _LOGGER.warning(f"Invalid virtual_power_usage for {id}: {self.virtual_power_usage} ({e})")
                self.virtual_power_usage = None
        super().__init__(id=id, name=name or id, topic_type=topic_type, topic_prefix=topic_prefix, **kwargs)
        self._output_type = output_type
        self._event_bus = event_bus
        self._interlock_manager = interlock_manager
        self._interlock_groups = interlock_groups
        if output_type == COVER:
            self._momentary_turn_on = None
            self._momentary_turn_off = None
        self._state = ON if restored_state else OFF
        # self._callback = callback
        self._momentary_action = None
        self._last_timestamp = 0.0
        self._loop = asyncio.get_running_loop()
        # --- Virtual energy counter ---
        self._energy_consumed_Wh = 0.0
        self._last_on_timestamp = time.time() if self._state == ON else None
        self._virtual_energy_topic = f"{topic_prefix}/energy/{self.id}"
        # Subscribe to retained MQTT energy value
        if self.virtual_power_usage is not None:
            self._virtual_energy_task = None
            self._subscribe_restore_energy_state()


    def set_interlock(self, interlock_manager: SoftwareInterlockManager, interlock_groups: list[str]):
        self._interlock_manager = interlock_manager
        self._interlock_groups = interlock_groups


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

    def _start_virtual_energy_task(self):
        """Start periodic task to update and send virtual energy state every 30 seconds."""
        if self._virtual_energy_task is not None and not self._virtual_energy_task.done():
            return  # Already running
        self._virtual_energy_task = self._loop.create_task(self._virtual_energy_loop())
        _LOGGER.info(f"Started periodic virtual energy task for {self.id}")

    def _stop_virtual_energy_task(self):
        """Stop periodic virtual energy update task."""
        if self._virtual_energy_task is not None:
            self._virtual_energy_task.cancel()
            self._virtual_energy_task = None
            self._update_virtual_energy()
            self.send_virtual_energy_state()
            _LOGGER.info(f"Stopped periodic virtual energy task for {self.id}")

    async def _virtual_energy_loop(self):
        """Periodically update and send virtual energy state every 30 seconds while relay is ON."""
        try:
            while self.state == ON:
                self._update_virtual_energy()
                self.send_virtual_energy_state()
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass

    def _update_virtual_energy(self):
        """Update energy counter if virtual_power_usage is set."""
        now = time.time()
        if self.state == ON and self._last_on_timestamp is not None:
            elapsed = now - self._last_on_timestamp
            self._energy_consumed_Wh += (self.virtual_power_usage * elapsed) / 3600.0
            self._last_on_timestamp = now
            _LOGGER.debug(f"Energy updated for {self.id}: {self._energy_consumed_Wh:.4f} Wh")

    def _subscribe_restore_energy_state(self):
        """
        Subscribe to the retained MQTT topic for energy and restore state if available.
        """
        import json
        async def on_energy_message(_topic, payload):
            try:
                payload = json.loads(payload)
                if isinstance(payload, dict) and "energy" in payload:
                    retained_energy_wh = float(payload["energy"])
                    self._energy_consumed_Wh = retained_energy_wh
                    _LOGGER.info(f"Restored energy state for {self.id} from MQTT: {self._energy_consumed_Wh:.4f} Wh")
                else:
                    _LOGGER.warning(f"Invalid retained payload for {self.id}: {payload}")
            except Exception as e:
                _LOGGER.warning(f"Failed to restore energy state for {self.id} from MQTT: {e}")
            finally:
                await self._message_bus.unsubscribe_and_stop_listen(self._virtual_energy_topic)
        # Subscribe (works for both LocalMessageBus and MQTTClient)
        if hasattr(self, '_message_bus') and self._message_bus is not None:
            asyncio.create_task(self._message_bus.subscribe_and_listen(self._virtual_energy_topic, on_energy_message))
        else:
            _LOGGER.warning(f"Message bus not available for {self.id}, cannot subscribe for retained energy.")

    def get_virtual_power(self) -> float:
        """Return current virtual power usage in W."""
        return self.virtual_power_usage if self.state == ON else 0.0

    def get_virtual_energy(self) -> float:
        """Return current virtual energy in Wh."""
        return round(self._energy_consumed_Wh, 3)

    def send_virtual_energy_state(self):
        """Send virtual power/energy state to MQTT for Home Assistant."""
        payload = {
            "power": self.get_virtual_power(),
            "energy": self.get_virtual_energy(),
        }
        self._message_bus.send_message(
            topic=f"{self._virtual_energy_topic}",
            payload=payload,
            retain=True,
        )
        _LOGGER.info(f"Sent virtual energy state for {self.id}: {payload}")

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
            self._message_bus.send_message(
                topic=self._send_topic,
                payload={STATE: state},
                retain=True,
            )
            if self.virtual_power_usage is not None:
                if state == ON:
                    self._last_on_timestamp = time.time()
                    self._start_virtual_energy_task()
                elif self._last_on_timestamp is not None:
                    self._stop_virtual_energy_task()
                    self._last_on_timestamp = None
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
        

    def check_interlock(self) -> bool:
        if getattr(self, "_interlock_manager", None) and getattr(self, "_interlock_groups", None):
            return self._interlock_manager.can_turn_on(self, self._interlock_groups)
        return True

    async def async_turn_on(self) -> None:
        """Turn on the relay asynchronously."""
        can_turn_on = self.check_interlock()
        if can_turn_on:
            self.turn_on()
        else:
            _LOGGER.warning(f"Interlock active: cannot turn on {self.id}.")
            #Workaround for HA is sendind state ON/OFF without physically changing the relay.
            asyncio.create_task(self.async_send_state(optimized_value=ON))
            return
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
