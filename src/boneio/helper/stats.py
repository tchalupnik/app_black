from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Callable
from datetime import timedelta
from math import floor
from typing import TYPE_CHECKING, Literal

import psutil
from pydantic import BaseModel, Field

from boneio.config import OledExtraScreenSensorConfig, OledScreens
from boneio.const import (
    CPU,
    DISK,
    GIGABYTE,
    IP,
    MAC,
    MASK,
    MEGABYTE,
    MEMORY,
    NETWORK,
    NONE,
    SWAP,
    UPTIME,
)
from boneio.events import EventBus, HostEvent
from boneio.models import HostSensorState
from boneio.relay.basic import BasicRelay
from boneio.sensor.temp import TempSensor

if TYPE_CHECKING:
    from boneio.gpio.base import GpioBase
    from boneio.manager import Manager
    from boneio.sensor import INA219

from boneio.helper.async_updater import AsyncUpdater
from boneio.version import __version__

_LOGGER = logging.getLogger(__name__)
intervals = (("d", 86400), ("h", 3600), ("m", 60))


def display_time(seconds: float) -> str:
    """Strf time."""
    result = []

    for name, count in intervals:
        value = seconds // count
        if value:
            seconds -= value * count
            if value == 1:
                name = name.rstrip("s")
            result.append(f"{int(value)}{name}")
    return "".join(result)


def get_network_info():
    """Fetch network info."""
    addrs = psutil.net_if_addrs().get("eth0", [])
    out = {IP: NONE, MASK: NONE, MAC: NONE}
    for addr in addrs:
        if addr.family == socket.AF_INET:
            out["ip"] = addr.address
            out["mask"] = addr.netmask if addr.netmask is not None else ""
        elif addr.family == psutil.AF_LINK:
            out["mac"] = addr.address
    return out


def get_cpu_info() -> dict[str, str]:
    """Fetch CPU info."""
    cpu = psutil.cpu_times_percent()
    return {
        "total": f"{int(100 - cpu.idle)}%",
        "user": f"{cpu.user}%",
        "system": f"{cpu.system}%",
    }


def get_disk_info() -> dict[str, str]:
    """Fetch disk info."""
    disk = psutil.disk_usage("/")
    return {
        "total": f"{floor(disk.total / GIGABYTE)}GB",
        "used": f"{floor(disk.used / GIGABYTE)}GB",
        "free": f"{floor(disk.free / GIGABYTE)}GB",
    }


def get_memory_info() -> dict[str, str]:
    """Fetch memory info."""
    vm = psutil.virtual_memory()
    return {
        "total": f"{floor(vm.total / MEGABYTE)}MB",
        "used": f"{floor(vm.used / MEGABYTE)}MB",
        "free": f"{floor(vm.available / MEGABYTE)}MB",
    }


def get_swap_info() -> dict[str, str]:
    """Fetch swap info."""
    swap = psutil.swap_memory()
    return {
        "total": f"{floor(swap.total / MEGABYTE)}MB",
        "used": f"{floor(swap.used / MEGABYTE)}MB",
        "free": f"{floor(swap.free / MEGABYTE)}MB",
    }


def get_uptime() -> str:
    """Fetch uptime info."""
    return display_time(time.clock_gettime(time.CLOCK_MONOTONIC))


class HostSensor(AsyncUpdater):
    """Host sensor."""

    def __init__(
        self,
        host_stat: HostStat,
        event_bus: EventBus,
        id: str,
        type: str,
        manager: Manager,
    ) -> None:
        self._state = {}
        self.host_stat = host_stat
        self._type = type
        self._event_bus = event_bus
        self._loop = asyncio.get_event_loop()
        self.id = id
        super().__init__(manager=manager, update_interval=host_stat.update_interval)
        self._loop.create_task(self.async_update(time.time()))

    async def async_update(self, timestamp: float) -> None:
        self._state = self.host_stat.f()
        self._event_bus.trigger_event(
            HostEvent(
                entity_id=self.id,
                event_state=HostSensorState(
                    id=self.id,
                    name=self._type,
                    state="new_state",  # doesn't matter here, as we fetch everything in Oled.
                    timestamp=timestamp,
                ),
            )
        )

    @property
    def state(self) -> dict[str, str]:
        if self.host_stat.static:
            return {
                **{k: v.model_dump() for k, v in self.host_stat.static.items()},
                **self._state,
            }
        return self._state


class FontSizeStatic(BaseModel):
    data: str
    fontSize: Literal["small", "medium", "large"]
    row: int
    col: int


class HostStat(BaseModel):
    f: Callable[[], dict[str, str]]
    update_interval: timedelta = Field(default=timedelta(seconds=60))
    static: dict[Literal["host", "ver"], FontSizeStatic] | None = None


class HostData:
    """Helper class to store host data."""

    def __init__(
        self,
        output: dict[str, dict[str, BasicRelay]],
        inputs: dict[str, GpioBase],
        temp_sensor: Callable[[TempSensor], None] | None,
        ina219: INA219 | None,
        manager: Manager,
        event_bus: EventBus,
        enabled_screens: list[OledScreens],
        extra_sensors: list[OledExtraScreenSensorConfig],
    ) -> None:
        """Initialize HostData."""
        self._manager = manager
        self._hostname = socket.gethostname()
        self._temp_sensor = temp_sensor
        host_stats: dict[str, HostStat] = {
            NETWORK: HostStat(f=get_network_info),
            CPU: HostStat(f=get_cpu_info, update_interval=timedelta(seconds=5)),
            DISK: HostStat(f=get_disk_info),
            MEMORY: HostStat(f=get_memory_info, update_interval=timedelta(seconds=10)),
            SWAP: HostStat(f=get_swap_info),
            UPTIME: HostStat(
                f=lambda: (
                    {
                        "uptime": {
                            "data": get_uptime(),
                            "fontSize": "small",
                            "row": 2,
                            "col": 3,
                        },
                        "MQTT": {
                            "data": "CONN"
                            if manager.message_bus.is_connection_established()
                            else "DOWN",
                            "fontSize": "small",
                            "row": 3,
                            "col": 60,
                        },
                        "T": {
                            "data": f"{self._temp_sensor.state} C",
                            "fontSize": "small",
                            "row": 3,
                            "col": 3,
                        },
                    }
                    if self._temp_sensor
                    else {
                        "uptime": {
                            "data": get_uptime(),
                            "fontSize": "small",
                            "row": 2,
                            "col": 3,
                        }
                    }
                ),
                static={
                    "host": FontSizeStatic(
                        data=self._hostname,
                        fontSize="small",
                        row=0,
                        col=3,
                    ),
                    "ver": FontSizeStatic(
                        data=__version__,
                        fontSize="small",
                        row=1,
                        col=3,
                    ),
                },
                update_interval=timedelta(seconds=30),
            ),
        }
        if ina219 is not None:

            def get_ina_values():
                return {
                    sensor.device_class: f"{sensor.state} {sensor.unit_of_measurement}"
                    for sensor in ina219.sensors.values()
                }

            host_stats["ina219"] = {
                "f": get_ina_values,
                "update_interval": timedelta(seconds=60),
            }
        if extra_sensors:

            def get_extra_sensors_values() -> dict:
                output = {}
                for sensor in extra_sensors:
                    if sensor.sensor_type == "modbus":
                        _modbus_coordinator = manager.modbus_coordinators.get(
                            sensor.modbus_id
                        )
                        if _modbus_coordinator:
                            entity = _modbus_coordinator.get_entity_by_name(
                                sensor.sensor_id
                            )
                            if not entity:
                                _LOGGER.warning("Sensor %s not found", sensor.sensor_id)
                                continue
                            short_name = "".join([x[:3] for x in entity.name.split()])
                            output[short_name] = (
                                f"{round(entity.state, 2)} {entity.unit_of_measurement}"
                            )
                    elif sensor.sensor_type == "dallas":
                        for single_sensor in manager.temp_sensors:
                            if sensor.sensor_id == single_sensor.id.lower():
                                output[single_sensor.name] = (
                                    f"{round(single_sensor.state, 2)} C"
                                )
                    else:
                        _LOGGER.warning(
                            "Sensor type %s not supported", sensor.sensor_type
                        )
                return output

            host_stats["extra_sensors"] = {
                "f": get_extra_sensors_values,
                "update_interval": timedelta(seconds=60),
            }
        self._data: dict[str, HostSensor] = {}
        for k, _v in host_stats.items():
            if k not in enabled_screens:
                continue
            self._data[k] = HostSensor(
                host_stat=_v,
                event_bus=event_bus,
                manager=manager,
                id=f"{k}_hoststats",
                type=k,
            )
        self._output = output
        self._inputs = {
            f"Inputs screen {i + 1}": list(inputs.values())[i * 25 : (i + 1) * 25]
            for i in range((len(inputs) + 24) // 25)
        }
        self._loop = asyncio.get_running_loop()

    @property
    def web_url(self) -> str | None:
        if self._manager.config.web is None:
            return None
        network_state = self._data[NETWORK].state
        if IP in network_state:
            return f"http://{network_state[IP]}:{self._manager.config.web.port}"
        return None

    def get(self, type: str) -> dict:
        """Get saved stats."""
        if type in self._output:
            return self._get_output(type)
        if type in self._inputs:
            return self._get_input(type)
        if type == "web":
            return self.web_url
        return self._data[type].state

    def _get_output(self, type: str) -> dict:
        """Get stats for output."""
        out = {}
        for output in self._output[type].values():
            out[output.id] = {"name": output.name, "state": output.state}

        return out

    def _get_input(self, type: str) -> dict:
        """Get stats for input."""
        inputs = {}
        for input in self._inputs[type]:
            inputs[input.pin] = {
                "name": input.name,
                "state": input.last_state[0].upper()
                if input.last_state and input.last_state != "Unknown"
                else "",
            }
        return inputs

    @property
    def inputs_length(self) -> int:
        return len(self._inputs)
