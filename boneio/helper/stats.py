from __future__ import annotations
import asyncio
import logging
from datetime import datetime
import socket
import time
from math import floor
from typing import Callable, List
from functools import partial

import psutil

from boneio.const import (
    CPU,
    DISK,
    GIGABYTE,
    INA219,
    IP,
    MAC,
    MASK,
    MEGABYTE,
    MEMORY,
    NETWORK,
    NONE,
    SWAP,
    UPTIME,
    HOST,
)

# Typing imports that create a circular dependency
from typing import TYPE_CHECKING

from boneio.helper.gpio import GpioBaseClass

if TYPE_CHECKING:
    from boneio.manager import Manager

from boneio.helper.async_updater import AsyncUpdater
from boneio.helper.timeperiod import TimePeriod
from boneio.sensor import LM75Sensor, MCP9808Sensor, INA219 as INA219Class
from boneio.version import __version__

_LOGGER = logging.getLogger(__name__)
intervals = (("d", 86400), ("h", 3600), ("m", 60))


def display_time(seconds):
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

    def retrieve_from_psutil():
        addrs = psutil.net_if_addrs()["eth0"]
        out = {IP: NONE, MASK: NONE, MAC: NONE}
        for addr in addrs:
            if addr.family == socket.AF_INET:
                out["ip"] = addr.address
                out["mask"] = addr.netmask if addr.netmask is not None else ""
            elif addr.family == psutil.AF_LINK:
                out["mac"] = addr.address
        return out

    return retrieve_from_psutil()


def get_cpu_info():
    """Fetch CPU info."""
    cpu = psutil.cpu_times_percent()
    return {
        "total": f"{int(100 - cpu.idle)}%",
        "user": f"{cpu.user}%",
        "system": f"{cpu.system}%",
    }


def get_disk_info():
    """Fetch disk info."""
    disk = psutil.disk_usage("/")
    return {
        "total": f"{floor(disk.total / GIGABYTE)}GB",
        "used": f"{floor(disk.used / GIGABYTE)}GB",
        "free": f"{floor(disk.free / GIGABYTE)}GB",
    }


def get_memory_info():
    """Fetch memory info."""
    vm = psutil.virtual_memory()
    return {
        "total": f"{floor(vm.total / MEGABYTE)}MB",
        "used": f"{floor(vm.used / MEGABYTE)}MB",
        "free": f"{floor(vm.available / MEGABYTE)}MB",
    }


def get_swap_info():
    """Fetch swap info."""
    swap = psutil.swap_memory()
    return {
        "total": f"{floor(swap.total / MEGABYTE)}MB",
        "used": f"{floor(swap.used / MEGABYTE)}MB",
        "free": f"{floor(swap.free / MEGABYTE)}MB",
    }


def get_uptime():
    """Fetch uptime info."""
    return display_time(time.clock_gettime(time.CLOCK_BOOTTIME))


class HostSensor(AsyncUpdater):
    """Host sensor."""

    def __init__(
        self,
        update_function: Callable,
        manager_callback: Callable,
        static_data: dict | None,
        id: str,
        type: str,
        **kwargs,
    ) -> None:
        self._update_function = update_function
        self._static_data = static_data
        self._state = {}
        self._type = type
        self._manager_callback = manager_callback
        self._loop = asyncio.get_event_loop()
        self.id = id
        super().__init__(**kwargs)

    async def async_update(self, time: datetime) -> None:
        self._state = self._update_function()
        self._loop.call_soon_threadsafe(
            partial(self._manager_callback, self._type)
        )

    @property
    def state(self) -> dict:
        if self._static_data:
            return {**self._static_data, **self._state}
        return self._state


class HostData:
    """Helper class to store host data."""

    def __init__(
        self,
        output: dict,
        inputs: dict[str, GpioBaseClass],
        callback: Callable,
        temp_sensor: Callable[[LM75Sensor, MCP9808Sensor], None] | None,
        ina219: INA219Class | None,
        manager: Manager,
        enabled_screens: List[str],
        extra_sensors: List[dict],
    ) -> None:
        """Initialize HostData."""
        self._hostname = socket.gethostname()
        self._temp_sensor = temp_sensor
        host_stats = {
            NETWORK: {
                "f": get_network_info,
                "update_interval": TimePeriod(seconds=60),
            },
            CPU: {"f": get_cpu_info, "update_interval": TimePeriod(seconds=5)},
            DISK: {
                "f": get_disk_info,
                "update_interval": TimePeriod(seconds=60),
            },
            MEMORY: {
                "f": get_memory_info,
                "update_interval": TimePeriod(seconds=10),
            },
            SWAP: {
                "f": get_swap_info,
                "update_interval": TimePeriod(seconds=60),
            },
            UPTIME: {
                "f": lambda: (
                    {
                        "uptime": {
                            "data": get_uptime(),
                            "fontSize": "small",
                            "row": 2,
                            "col": 3,
                        },
                        "MQTT": {
                            "data": "CONN" if manager.mqtt_state else "DOWN",
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
                "static": {
                    HOST: {
                        "data": self._hostname,
                        "fontSize": "small",
                        "row": 0,
                        "col": 3,
                    },
                    "ver": {
                        "data": __version__,
                        "fontSize": "small",
                        "row": 1,
                        "col": 3,
                    },
                },
                "update_interval": TimePeriod(seconds=30),
            },
        }
        if ina219 is not None:

            def get_ina_values():
                return {
                    sensor.device_class: f"{sensor.state} {sensor.unit_of_measurement}"
                    for sensor in ina219.sensors.values()
                }

            host_stats[INA219] = {
                "f": get_ina_values,
                "update_interval": TimePeriod(seconds=60),
            }
        if extra_sensors:

            def get_extra_sensors_values():
                output = {}
                for sensor in extra_sensors[:3]:
                    sensor_type = sensor.get("sensor_type")
                    sensor_id = sensor.get("sensor_id")
                    if sensor_type == "modbus":
                        modbus_id = sensor.get("modbus_id")
                        _modbus_sensors = manager.modbus_sensors.get(modbus_id)
                        if _modbus_sensors:
                            single_sensor = _modbus_sensors.get_sensor_by_name(
                                sensor_id
                            )
                            if not single_sensor:
                                _LOGGER.warning(
                                    "Sensor %s not found", sensor_id
                                )
                                continue
                            short_name = "".join(
                                [x[:3] for x in single_sensor.name.split()]
                            )
                            output[short_name] = (
                                f"{round(single_sensor.state, 2)} {single_sensor.unit_of_measurement}"
                            )
                    elif sensor_type == "dallas":
                        for single_sensor in manager.temp_sensors:
                            if sensor_id == single_sensor.id.lower():
                                output[single_sensor.name] = (
                                    f"{round(single_sensor.state, 2)} C"
                                )
                return output

            host_stats["extra_sensors"] = {
                "f": get_extra_sensors_values,
                "update_interval": TimePeriod(seconds=60),
            }
        self._data = {}
        for k, _v in host_stats.items():
            if k not in enabled_screens:
                continue
            self._data[k] = HostSensor(
                update_function=_v["f"],
                static_data=_v.get("static"),
                manager=manager,
                manager_callback=callback,
                id=f"{k}_hoststats",
                type=k,
                update_interval=_v["update_interval"],
            )
        self._output = output
        self._inputs = {
            f"Inputs screen {i + 1}": list(inputs.values())[
                i * 25 : (i + 1) * 25
            ]
            for i in range((len(inputs) + 24) // 25)
        }
        self._callback = callback
        self._loop = asyncio.get_running_loop()

    def get(self, type: str) -> dict:
        """Get saved stats."""
        if type in self._output:
            return self._get_output(type)
        if type in self._inputs:
            return self._get_input(type)
        return self._data[type].state

    def _get_output(self, type: str) -> dict:
        """Get stats for output."""
        out = {}
        for output in self._output[type].values():
            out[output.id] = output.state
        return out

    def _get_input(self, type: str) -> dict:
        """Get stats for input."""
        inputs = {}
        for input in self._inputs[type]:
            inputs[input.name] = (
                input.pressed_state[0].upper() if input.pressed_state else ""
            )
        return inputs

    @property
    def inputs_length(self) -> int:
        return len(self._inputs)
