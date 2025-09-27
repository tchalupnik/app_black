"""Basic Relay module."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

import anyio
from pydantic import BaseModel, ValidationError

from boneio.config import OutputTypes
from boneio.const import ON, STATE
from boneio.events import EventBus, OutputEvent, async_track_point_in_time, utcnow
from boneio.helper.interlock import SoftwareInterlockManager
from boneio.helper.util import strip_accents
from boneio.message_bus.basic import MessageBus
from boneio.models import OutputState

_LOGGER = logging.getLogger(__name__)


@dataclass
class _VirtualEnergySensor:
    id: str
    parent: BasicRelay
    message_bus: MessageBus
    topic_prefix: str
    virtual_power_usage: float | None = None
    virtual_volume_flow_rate: float | None = None
    last_on_timestamp: float | None = None

    energy_consumed_Wh = 0.0
    water_consumed_L = 0.0

    def __post_init__(self):
        self._virtual_sensors_task = None
        self.virtual_energy_topic = f"{self.topic_prefix}/energy/{self.id}"
        self._subscribe_restore_energy_state()
        self._loop = asyncio.get_running_loop()

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
        _LOGGER.info("Started periodic virtual sensors task for %s", self.id)

    def stop_virtual_sensors_task(self):
        """Stop periodic virtual energy update task."""
        self.last_on_timestamp = None
        if self._virtual_sensors_task is not None:
            self._virtual_sensors_task.cancel()
            self._virtual_sensors_task = None
            self._update_virtual_sensors()
            _LOGGER.info("Stopped periodic virtual sensors task for %s", self.id)

    async def _virtual_sensors_loop(self):
        """Periodically update and send virtual energy state every 30 seconds while relay is ON."""
        while self.parent.state == "ON":
            self._update_virtual_sensors()
            await anyio.sleep(30)

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
        if self.parent.state == ON and self.last_on_timestamp is not None:
            elapsed = now - self.last_on_timestamp
            if self.virtual_power_usage is not None:
                self.energy_consumed_Wh += (self.virtual_power_usage * elapsed) / 3600.0
                _LOGGER.debug(
                    "Energy updated for %s: %.4f Wh",
                    self.parent.id,
                    self.energy_consumed_Wh,
                )
            if self.virtual_volume_flow_rate is not None:
                self.water_consumed_L += (
                    self.virtual_volume_flow_rate * elapsed
                ) / 3600.0
                _LOGGER.debug(
                    "Volume flow rate updated for %s: %.4f L",
                    self.parent.id,
                    self.water_consumed_L,
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
                    self.energy_consumed_Wh = energy_message.energy
                    _LOGGER.info(
                        "Restored energy state for %s from MQTT: %.4f Wh",
                        self.id,
                        self.energy_consumed_Wh,
                    )
                if energy_message.water is not None:
                    self.water_consumed_L = energy_message.water
                    _LOGGER.info(
                        "Restored water consumption state for %s from MQTT: %.4f L",
                        self.id,
                        self.water_consumed_L,
                    )
            except ValidationError as e:
                _LOGGER.warning(
                    "Failed to restore energy state for %s from MQTT: %s",
                    self.id,
                    str(e),
                )
            finally:
                await self.message_bus.unsubscribe_and_stop_listen(
                    self.virtual_energy_topic
                )

        # Subscribe (works for both LocalMessageBus and MQTTClient)
        asyncio.create_task(
            self.message_bus.subscribe_and_listen(
                self.virtual_energy_topic, on_energy_message
            )
        )

    def send_virtual_energy_state(self):
        """Send virtual power/energy state to MQTT for Home Assistant."""
        payload = {}
        if self.virtual_power_usage is not None:
            payload["power"] = (
                self.virtual_power_usage if self.parent.state == "ON" else 0.0
            )
            payload["energy"] = round(self.energy_consumed_Wh, 3)
        if self.virtual_volume_flow_rate is not None:
            payload["volume_flow_rate"] = (
                self.virtual_volume_flow_rate if self.parent.state == "ON" else 0.0
            )
            payload["water"] = round(self.water_consumed_L, 3)
        self.message_bus.send_message(
            topic=self.virtual_energy_topic,
            payload=payload,
            retain=True,
        )
        _LOGGER.info("Sent virtual energy state for %s: %s", self.id, payload)


class _EnergyMessage(BaseModel):
    energy: float | None = None
    water: float | None = None


@dataclass
class BasicRelay(ABC):
    """Basic relay class."""

    id: str
    pin_id: int
    event_bus: EventBus
    topic_prefix: str
    message_bus: MessageBus
    expander_id: str
    name: str | None = None
    output_type: OutputTypes = "switch"
    restored_state: bool = False
    topic_type: str = "relay"
    interlock_manager: SoftwareInterlockManager | None = None
    interlock_groups: list[str] = field(default_factory=list)
    momentary_turn_on: timedelta | None = None
    momentary_turn_off: timedelta | None = None
    virtual_power_usage: float | None = None
    virtual_volume_flow_rate: float | None = None
    last_timestamp: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        """Initialize Basic relay.
        Supports virtual_power_usage for energy monitoring.
        """
        # No parsing needed, Cerberus coerce handles conversion to watts.
        self.id = self.id.replace(" ", "")

        if self.name is None:
            self.name = self.id
        self._send_topic = (
            f"{self.topic_prefix}/{self.topic_type}/{strip_accents(self.id)}"
        )
        if self.output_type == "cover":
            self.momentary_turn_on = None
            self.momentary_turn_off = None
        self.state: Literal["ON", "OFF"] = "ON" if self.restored_state else "OFF"
        self.momentary_action = None

        # Subscribe to retained MQTT energy value
        self.virtual_energy_sensor = None
        if (
            self.virtual_power_usage is not None
            or self.virtual_volume_flow_rate is not None
        ):
            self.virtual_energy_sensor = _VirtualEnergySensor(
                id=self.id,
                message_bus=self.message_bus,
                topic_prefix=self.topic_prefix,
                parent=self,
                virtual_power_usage=self.virtual_power_usage,
                virtual_volume_flow_rate=self.virtual_volume_flow_rate,
                last_on_timestamp=time.time() if self.state == "ON" else None,
            )
            self._virtual_sensors_task = None

    @property
    def is_virtual_power(self) -> bool:
        return (
            self.virtual_energy_sensor is not None
            and self.virtual_energy_sensor.virtual_power_usage is not None
        )

    @property
    def is_virtual_volume_flow_rate(self) -> bool:
        return (
            self.virtual_energy_sensor is not None
            and self.virtual_energy_sensor.virtual_volume_flow_rate is not None
        )

    def payload(self) -> dict:
        return {STATE: self.state}

    def send_state(self, optimized_value: str | None = None) -> None:
        """Send state to Mqtt on action asynchronously."""
        if optimized_value:
            state = optimized_value
        else:
            state = "ON" if self.is_active() else "OFF"
        self.state = state
        if self.output_type not in ("cover", "none"):
            self.message_bus.send_message(
                topic=self._send_topic,
                payload={STATE: state},
                retain=True,
            )
            if self.virtual_energy_sensor and not optimized_value:
                if state == "ON":
                    self.virtual_energy_sensor.start_virtual_sensors_task()
                elif self.virtual_energy_sensor.last_on_timestamp is not None:
                    self.virtual_energy_sensor.stop_virtual_sensors_task()
        if optimized_value:
            return
        self.last_timestamp = time.time()
        self.event_bus.trigger_event(
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
        if self.interlock_manager is not None and self.interlock_groups:
            return self.interlock_manager.can_turn_on(self, self.interlock_groups)
        return True

    def turn_on(self) -> None:
        """Turn on the relay asynchronously."""
        can_turn_on = self.check_interlock()
        if can_turn_on:
            _LOGGER.info("Turning on relay %s.", self.name)
            self._turn_on()
            self.state = "ON"
            self._execute_momentary_turn(momentary_type="ON")
        else:
            _LOGGER.warning("Interlock active: cannot turn on %s.", self.id)
            # Workaround for HA is sendind state ON/OFF without physically changing the relay.
            self.send_state(optimized_value=ON)
            # await anyio.sleep(0.01)
        self.send_state()

    def turn_off(self) -> None:
        """Turn off the relay asynchronously."""
        _LOGGER.info("Turning off relay %s.", self.name)
        self._turn_off()
        self.state = "OFF"
        self._execute_momentary_turn(momentary_type="OFF")
        self.send_state()

    def toggle(self) -> None:
        """Toggle relay."""
        now = time.time()
        _LOGGER.debug("Toggle relay %s, state: %s, at %s.", self.name, self.state, now)
        if self.state == "ON":
            self.turn_off()
        else:
            self.turn_on()

    @abstractmethod
    def _turn_on(self) -> None:
        """Call turn on action."""
        raise NotImplementedError

    @abstractmethod
    def _turn_off(self) -> None:
        """Call turn off action."""
        raise NotImplementedError

    def _execute_momentary_turn(self, momentary_type: Literal["ON", "OFF"]) -> None:
        """Execute momentary action."""
        if self.momentary_action:
            _LOGGER.debug("Cancelling momentary action for %s", self.name)
            self.momentary_action()
        (action, delayed_action) = (
            (self.turn_off, self.momentary_turn_on)
            if momentary_type == "ON"
            else (self.turn_on, self.momentary_turn_off)
        )
        if delayed_action is not None:
            _LOGGER.debug(
                "Applying momentary action for %s in %s",
                self.name,
                delayed_action,
            )
            self.momentary_action = async_track_point_in_time(
                job=self._momentary_callback,
                point_in_time=utcnow() + delayed_action,
                action=action,
            )

    async def _momentary_callback(self, timestamp, action):
        _LOGGER.info("Momentary callback at %s for output %s", timestamp, self.name)
        await action(timestamp=timestamp)
        self.momentary_action = None

    @abstractmethod
    def is_active(self) -> bool:
        """Is active check."""
        raise NotImplementedError
