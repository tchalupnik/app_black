"""Basic Relay module."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

from pydantic import BaseModel, ValidationError

from boneio.const import COVER, LIGHT, NONE, OFF, ON, RELAY, STATE, SWITCH
from boneio.events import EventBus, OutputEvent, async_track_point_in_time, utcnow
from boneio.helper.interlock import SoftwareInterlockManager
from boneio.helper.util import strip_accents
from boneio.message_bus.basic import MessageBus
from boneio.models import OutputState

_LOGGER = logging.getLogger(__name__)


class _VirtualEnergySensor:
    def __init__(
        self,
        message_bus: MessageBus,
        loop: asyncio.AbstractEventLoop,
        topic_prefix: str,
        parent: BasicRelay,
        virtual_power_usage: float | None = None,
        virtual_volume_flow_rate: float | None = None,
    ):
        self._loop = loop
        self._message_bus = message_bus
        self._virtual_sensors_task = None
        self._parent = parent
        self.virtual_power_usage = virtual_power_usage
        self.virtual_volume_flow_rate = virtual_volume_flow_rate
        # --- Virtual energy counter ---
        self._energy_consumed_Wh = 0.0
        self._water_consumed_L = 0.0
        self.last_on_timestamp = time.time() if self._parent.state == ON else None
        self._virtual_energy_topic = f"{topic_prefix}/energy/{self._parent.id}"
        self._subscribe_restore_energy_state()

    def start_virtual_sensors_task(self):
        """Start periodic task to update and send virtual energy state every 30 seconds."""
        self.last_on_timestamp = time.time()
        if (
            self._virtual_sensors_task is not None
            and not self._virtual_sensors_task.done()
        ):
            return  # Already running
        self._virtual_sensors_task = self._loop.create_task(
            self._virtual_sensors_loop()
        )
        _LOGGER.info("Started periodic virtual sensors task for %s", self._parent.id)

    def stop_virtual_sensors_task(self):
        """Stop periodic virtual energy update task."""
        self.last_on_timestamp = None
        if self._virtual_sensors_task is not None:
            self._virtual_sensors_task.cancel()
            self._virtual_sensors_task = None
            self._update_virtual_sensors()
            _LOGGER.info(
                "Stopped periodic virtual sensors task for %s", self._parent.id
            )

    async def _virtual_sensors_loop(self):
        """Periodically update and send virtual energy state every 30 seconds while relay is ON."""
        try:
            while self._parent.state == ON:
                self._update_virtual_sensors()
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass

    def _update_virtual_sensors(self):
        """Update virtual sensors if virtual_power_usage is set."""
        if (
            self.virtual_power_usage is not None
            or self.virtual_volume_flow_rate is not None
        ):
            self._update_virtual_energy()
            self.send_virtual_energy_state()

    def _update_virtual_energy(self):
        """Update energy counter if virtual_power_usage is set."""
        now = time.time()
        if self._parent.state == ON and self.last_on_timestamp is not None:
            elapsed = now - self.last_on_timestamp
            if self.virtual_power_usage is not None:
                self._energy_consumed_Wh += (
                    self.virtual_power_usage * elapsed
                ) / 3600.0
                _LOGGER.debug(
                    "Energy updated for %s: %.4f Wh",
                    self._parent.id,
                    self._energy_consumed_Wh,
                )
            if self.virtual_volume_flow_rate is not None:
                self._water_consumed_L += (
                    self.virtual_volume_flow_rate * elapsed
                ) / 3600.0
                _LOGGER.debug(
                    "Volume flow rate updated for %s: %.4f L",
                    self._parent.id,
                    self._water_consumed_L,
                )
            self.last_on_timestamp = now

    def _subscribe_restore_energy_state(self):
        """
        Subscribe to the retained MQTT topic for energy and restore state if available.
        """

        async def on_energy_message(payload: str) -> None:
            try:
                energy_message = _EnergyMessage.model_validate_json(payload)
                if energy_message.energy is not None:
                    self._energy_consumed_Wh = energy_message.energy
                    _LOGGER.info(
                        "Restored energy state for %s from MQTT: %.4f Wh",
                        self._parent.id,
                        self._energy_consumed_Wh,
                    )
                if energy_message.water is not None:
                    self._water_consumed_L = energy_message.water
                    _LOGGER.info(
                        "Restored water consumption state for %s from MQTT: %.4f L",
                        self._parent.id,
                        self._water_consumed_L,
                    )
            except ValidationError as e:
                _LOGGER.warning(
                    "Failed to restore energy state for %s from MQTT: %s",
                    self._parent.id,
                    str(e),
                )
            finally:
                await self._message_bus.unsubscribe_and_stop_listen(
                    self._virtual_energy_topic
                )

        # Subscribe (works for both LocalMessageBus and MQTTClient)
        asyncio.create_task(
            self._message_bus.subscribe_and_listen(
                self._virtual_energy_topic, on_energy_message
            )
        )

    def send_virtual_energy_state(self):
        """Send virtual power/energy state to MQTT for Home Assistant."""
        payload = {}
        if self.virtual_power_usage is not None:
            payload["power"] = (
                self.virtual_power_usage if self._parent.state == ON else 0.0
            )
            payload["energy"] = round(self._energy_consumed_Wh, 3)
        if self.virtual_volume_flow_rate is not None:
            payload["volume_flow_rate"] = (
                self.virtual_volume_flow_rate if self._parent.state == ON else 0.0
            )
            payload["water"] = round(self._water_consumed_L, 3)
        self._message_bus.send_message(
            topic=self._virtual_energy_topic,
            payload=payload,
            retain=True,
        )
        _LOGGER.info("Sent virtual energy state for %s: %s", self._parent.id, payload)


class _EnergyMessage(BaseModel):
    energy: float | None = None
    water: float | None = None


class BasicRelay:
    """Basic relay class."""

    def __init__(
        self,
        id: str,
        pin_id: int,
        event_bus: EventBus,
        topic_prefix: str,
        message_bus: MessageBus,
        expander_id: str,
        name: str | None = None,
        output_type: str = SWITCH,
        restored_state: bool = False,
        topic_type: str = RELAY,
        interlock_manager: SoftwareInterlockManager | None = None,
        interlock_groups: list[str] | None = None,
        momentary_turn_on: timedelta | None = None,
        momentary_turn_off: timedelta | None = None,
        virtual_power_usage: float | None = None,
        virtual_volume_flow_rate: float | None = None,
    ) -> None:
        """Initialize Basic relay.
        Supports virtual_power_usage for energy monitoring.
        """
        # No parsing needed, Cerberus coerce handles conversion to watts.

        self.name = name or id
        self.id = id.replace(" ", "")
        self.message_bus = message_bus
        self._send_topic = f"{topic_prefix}/{topic_type}/{strip_accents(self.id)}"
        self.expander_id = expander_id
        self.pin_id = pin_id
        self._momentary_turn_off = momentary_turn_off
        self._momentary_turn_on = momentary_turn_on
        self.output_type = output_type
        self._event_bus = event_bus
        self._interlock_manager = interlock_manager
        self._interlock_groups = [] if interlock_groups is None else interlock_groups
        if output_type == COVER:
            self._momentary_turn_on = None
            self._momentary_turn_off = None
        self.state = ON if restored_state else OFF
        self._momentary_action = None
        self.last_timestamp = 0.0
        self._loop = asyncio.get_running_loop()

        # Subscribe to retained MQTT energy value
        self._virtual_energy_sensor = None
        if virtual_power_usage is not None or virtual_volume_flow_rate is not None:
            self._virtual_energy_sensor = _VirtualEnergySensor(
                message_bus=self.message_bus,
                loop=self._loop,
                topic_prefix=topic_prefix,
                parent=self,
                virtual_power_usage=virtual_power_usage,
                virtual_volume_flow_rate=virtual_volume_flow_rate,
            )
            self._virtual_sensors_task = None

    def set_interlock(
        self, interlock_manager: SoftwareInterlockManager, interlock_groups: list[str]
    ):
        self._interlock_manager = interlock_manager
        self._interlock_groups = interlock_groups

    @property
    def is_virtual_power(self) -> bool:
        return (
            self._virtual_energy_sensor is not None
            and self._virtual_energy_sensor.virtual_power_usage is not None
        )

    @property
    def is_virtual_volume_flow_rate(self) -> bool:
        return (
            self._virtual_energy_sensor is not None
            and self._virtual_energy_sensor.virtual_volume_flow_rate is not None
        )

    @property
    def is_light(self) -> bool:
        """Check if HA type is light"""
        return self.output_type == LIGHT

    def payload(self) -> dict:
        return {STATE: self.state}

    async def async_send_state(self, optimized_value: str | None = None) -> None:
        """Send state to Mqtt on action asynchronously."""
        if optimized_value:
            state = optimized_value
        else:
            state = ON if self.is_active else OFF
        self.state = state
        if self.output_type not in (COVER, NONE):
            self.message_bus.send_message(
                topic=self._send_topic,
                payload={STATE: state},
                retain=True,
            )
            if self._virtual_energy_sensor and not optimized_value:
                if state == ON:
                    self._virtual_energy_sensor.start_virtual_sensors_task()
                elif self._virtual_energy_sensor.last_on_timestamp is not None:
                    self._virtual_energy_sensor.stop_virtual_sensors_task()
        if optimized_value:
            return
        self.last_timestamp = time.time()
        self._event_bus.trigger_event(
            OutputEvent(
                entity_id=self.id,
                event_state=OutputState(
                    id=self.id,
                    name=self.name,
                    state=state,
                    type=self.output_type,
                    pin=self.pin_id,
                    timestamp=self.last_timestamp,
                    expander_id=self.expander_id,
                ),
            )
        )

    def check_interlock(self) -> bool:
        if self._interlock_manager is not None and self._interlock_groups:
            return self._interlock_manager.can_turn_on(self, self._interlock_groups)
        return True

    async def async_turn_on(self, timestamp=None) -> None:
        """Turn on the relay asynchronously."""
        can_turn_on = self.check_interlock()
        if can_turn_on:
            await self._loop.run_in_executor(None, self.turn_on, timestamp)
        else:
            _LOGGER.warning("Interlock active: cannot turn on %s.", self.id)
            # Workaround for HA is sendind state ON/OFF without physically changing the relay.
            asyncio.create_task(self.async_send_state(optimized_value=ON))
            await asyncio.sleep(0.01)
        asyncio.create_task(self.async_send_state())

    async def async_turn_off(self, timestamp=None) -> None:
        """Turn off the relay asynchronously."""
        await self._loop.run_in_executor(None, self.turn_off, timestamp)
        await self.async_send_state()

    async def async_toggle(self, timestamp=None) -> None:
        """Toggle relay."""
        now = time.time()
        _LOGGER.debug("Toggle relay %s, state: %s, at %s.", self.name, self.state, now)
        if self.state == ON:
            await self.async_turn_off(timestamp=timestamp)
        else:
            await self.async_turn_on(timestamp=timestamp)

    def turn_on(self, timestamp=None) -> None:
        """Call turn on action."""
        raise NotImplementedError

    def turn_off(self, timestamp=None) -> None:
        """Call turn off action."""
        raise NotImplementedError

    def _execute_momentary_turn(self, momentary_type: str) -> None:
        """Execute momentary action."""
        if self._momentary_action:
            _LOGGER.debug("Cancelling momentary action for %s", self.name)
            self._momentary_action()
        (action, delayed_action) = (
            (self.async_turn_off, self._momentary_turn_on)
            if momentary_type == ON
            else (self.async_turn_on, self._momentary_turn_off)
        )
        if delayed_action:
            _LOGGER.debug(
                "Applying momentary action for %s in %s",
                self.name,
                delayed_action,
            )
            self._momentary_action = async_track_point_in_time(
                loop=self._loop,
                job=self._momentary_callback,
                point_in_time=utcnow() + delayed_action,
                action=action,
            )

    async def _momentary_callback(self, timestamp, action):
        _LOGGER.info("Momentary callback at %s for output %s", timestamp, self.name)
        await action(timestamp=timestamp)
        self._momentary_action = None

    @property
    def is_active(self) -> bool:
        """Is active check."""
        raise NotImplementedError
