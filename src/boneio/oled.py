from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import partial
from itertools import cycle
from math import floor
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import anyio.abc
import psutil
import qrcode
from luma.core.error import DeviceNotFoundError
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from boneio.config import Config, OledScreens
from boneio.events import EventBus, EventType, HostEvent
from boneio.gpio_manager import Edge
from boneio.gpio_manager.base import GpioManagerBase
from boneio.helper import I2CError
from boneio.message_bus.basic import MessageBus
from boneio.modbus.coordinator import ModbusCoordinator
from boneio.models import HostSensorState, InputState, OutputState, SensorState
from boneio.relay.basic import BasicRelay
from boneio.sensor.temp import TempSensor
from boneio.version import __version__

if TYPE_CHECKING:
    from boneio.gpio import GpioEventButtonsAndSensors
    from boneio.sensor import INA219

_LOGGER = logging.getLogger(__name__)

OLED_PIN = "P9_23"

START_ROW = 17
UPTIME_ROWS = list(range(22, 60, 10))
OUTPUT_ROWS = list(range(14, 60, 6))
INPUT_ROWS = list(range(12, 60, 6))
OUTPUT_COLS = range(0, 113, 56)
INPUT_COLS = range(0, 113, 30)

GIGABYTE = 1073741824
MEGABYTE = 1048576

intervals = (("d", 86400), ("h", 3600), ("m", 60))

fonts = {
    "big": ImageFont.truetype("DejaVuSans.ttf", 12),
    "small": ImageFont.truetype("DejaVuSans.ttf", 9),
    "extraSmall": ImageFont.truetype("DejaVuSans.ttf", 7),
    "danube": ImageFont.truetype(Path(__file__).parent / "fonts" / "danube__.ttf", 15),
}


def shorten_name(name: str) -> str:
    if len(name) > 6:
        return f"{name[:4]}{name[-2:]}"
    return name


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


def get_network_info() -> dict[str, str]:
    """Fetch network info."""
    addrs = psutil.net_if_addrs().get("eth0", [])
    out = {"ip": "none", "mask": "none", "mac": "none"}
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


@dataclass
class HostSensor:
    """Host sensor."""

    host_stat: HostStat
    event_bus: EventBus
    id: str
    name: str
    _state: dict[str, str] = field(default_factory=dict)

    def update(self, timestamp: float) -> None:
        self._state = self.host_stat.f()
        self.event_bus.trigger_event(
            HostEvent(
                entity_id=self.id,
                event_state=HostSensorState(
                    id=self.id,
                    name=self.name,
                    state="new_state",  # doesn't matter here, as we fetch everything in Oled.
                    timestamp=timestamp,
                ),
            )
        )

    def get_state(self) -> dict[str, str]:
        if self.host_stat.static is not None:
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


@dataclass
class HostData:
    """Helper class to store host data."""

    message_bus: MessageBus
    event_bus: EventBus
    config: Config
    output: dict[str, dict[str, BasicRelay]]
    inputs: dict[str, GpioEventButtonsAndSensors]
    temp_sensors: list[TempSensor]
    ina219: INA219 | None
    modbus_coordinators: dict[str, ModbusCoordinator]
    _hostname: str = field(default_factory=socket.gethostname, init=False)

    def __post_init__(self) -> None:
        """Initialize HostData."""
        oled_config = self.config.oled
        assert oled_config is not None

        host_stats: dict[str, HostStat] = {
            "network": HostStat(f=get_network_info),
            "cpu": HostStat(f=get_cpu_info, update_interval=timedelta(seconds=5)),
            "disk": HostStat(f=get_disk_info),
            "memory": HostStat(
                f=get_memory_info, update_interval=timedelta(seconds=10)
            ),
            "swap": HostStat(f=get_swap_info),
            "uptime": HostStat(
                f=lambda: (
                    {
                        "uptime": FontSizeStatic(
                            data=get_uptime(),
                            fontSize="small",
                            row=2,
                            col=3,
                        ),
                        "MQTT": FontSizeStatic(
                            data="CONN"
                            if self.message_bus.is_connection_established()
                            else "DOWN",
                            fontSize="small",
                            row=3,
                            col=60,
                        ),
                        "T": FontSizeStatic(
                            data=f"{self._any_temp_sensor_value} C",
                            fontSize="small",
                            row=3,
                            col=3,
                        ),
                    }
                    if self.temp_sensors
                    else {
                        "uptime": FontSizeStatic(
                            data=get_uptime(),
                            fontSize="small",
                            row=2,
                            col=3,
                        ),
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
        if self.ina219 is not None:

            def get_ina_values(ina219: INA219) -> dict[str, str]:
                return {
                    sensor.device_class: f"{sensor.state} {sensor.unit_of_measurement}"
                    for sensor in ina219.sensors.values()
                }

            host_stats["ina219"] = HostStat(
                f=partial(get_ina_values, self.ina219),
                update_interval=timedelta(seconds=60),
            )
        if oled_config.extra_screen_sensors:

            def get_extra_sensors_values() -> dict[str, str]:
                output: dict[str, str] = {}
                for sensor in oled_config.extra_screen_sensors:
                    if sensor.sensor_type == "modbus":
                        _modbus_coordinator = self.modbus_coordinators.get(
                            sensor.modbus_id
                        )
                        if _modbus_coordinator is not None:
                            entity = _modbus_coordinator.get_entity_by_name(
                                sensor.sensor_id
                            )
                            if entity is None:
                                _LOGGER.warning("Sensor %s not found", sensor.sensor_id)
                                continue
                            short_name = "".join([x[:3] for x in entity.name.split()])
                            output[short_name] = (
                                f"{round(entity.state, 2)} {entity.unit_of_measurement}"
                            )
                    elif sensor.sensor_type == "dallas":
                        for single_sensor in self.temp_sensors:
                            if sensor.sensor_id == single_sensor.id.lower():
                                output[single_sensor.name] = (
                                    f"{round(single_sensor.state, 2)} C"
                                )
                    else:
                        _LOGGER.warning(
                            "Sensor type %s not supported", sensor.sensor_type
                        )
                return output

            host_stats["extra_sensors"] = HostStat(
                f=get_extra_sensors_values,
                update_interval=timedelta(seconds=60),
            )
        self.host_sensors: dict[str, HostSensor] = {}
        for host_stat_name, host_stat in host_stats.items():
            if host_stat_name not in oled_config.screens:
                continue
            sensor = HostSensor(
                host_stat=host_stat,
                event_bus=self.event_bus,
                id=f"{host_stat_name}_hoststats",
                name=host_stat_name,
            )
            self.host_sensors[host_stat_name] = sensor
        self.inputs_grouped = {
            f"Inputs screen {i + 1}": list(self.inputs.values())[i * 25 : (i + 1) * 25]
            for i in range((len(self.inputs) + 24) // 25)
        }

    @property
    def _any_temp_sensor_value(self) -> float | None:
        if self.temp_sensors:
            return self.temp_sensors[0].state
        return None

    @property
    def web_url(self) -> str | None:
        if self.config.web is None:
            return None
        network_state = self.host_sensors["network"].get_state()
        if "ip" in network_state:
            return f"http://{network_state['ip']}:{self.config.web.port}"
        return None

    def get(
        self, type: str
    ) -> dict[str, dict[str, str | None]] | dict[str, str] | str | None:
        """Get saved stats."""
        if type in self.output:
            return self._get_output(type)
        if type in self.inputs:
            return self._get_input(type)
        if type == "web":
            return self.web_url
        return self.host_sensors[type].get_state()

    def _get_output(self, type: str) -> dict[str, dict[str, str | None]]:
        """Get stats for output."""
        out = {}
        for output in self.output[type].values():
            out[output.id] = {"name": output.name, "state": output.state}

        return out

    def _get_input(self, type: str) -> dict[str, dict[str, str]]:
        """Get stats for input."""
        inputs = {}
        for input in self.inputs_grouped[type]:
            inputs[input.pin] = {
                "name": input.name,
                "state": input.last_state[0].upper()
                if input.last_state and input.last_state != "Unknown"
                else "",
            }
        return inputs


@dataclass
class Oled:
    """Oled display class."""

    tg: anyio.abc.TaskGroup
    config: Config
    event_bus: EventBus
    message_bus: MessageBus
    gpio_manager: GpioManagerBase
    grouped_outputs_by_expander: list[str]
    output: dict[str, dict[str, BasicRelay]]
    inputs: dict[str, GpioEventButtonsAndSensors]
    temp_sensors: list[TempSensor]
    ina219: INA219 | None
    modbus_coordinators: dict[str, ModbusCoordinator]
    screen_order: list[OledScreens] = field(init=False)
    host_data: HostData = field(init=False)
    sleep_timeout: timedelta = field(init=False)
    sleep_event: anyio.Event = field(default_factory=anyio.Event, init=False)
    sleep: bool = field(default=False, init=False)
    input_groups: list[str] = field(default_factory=list, init=False)
    press_time_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc), init=False
    )

    def __post_init__(self) -> None:
        """Initialize OLED screen."""
        assert self.config.oled is not None

        self.screen_order = self.config.oled.screens.copy()
        self.sleep_timeout = self.config.oled.screensaver_timeout

        self.host_data = HostData(
            message_bus=self.message_bus,
            event_bus=self.event_bus,
            config=self.config,
            output=self.grouped_outputs_by_expander,
            inputs=self.inputs,
            temp_sensors=self.temp_sensors,
            ina219=self.ina219,
            modbus_coordinators=self.modbus_coordinators,
        )

        def configure_outputs() -> None:
            try:
                _ind_screen = self.screen_order.index("outputs")
                if not self.grouped_outputs_by_expander:
                    _LOGGER.debug("No outputs configured. Omitting in screen.")
                    return
                self.screen_order.pop(_ind_screen)
                self.screen_order[_ind_screen:_ind_screen] = (
                    self.grouped_outputs_by_expander
                )
                self.grouped_outputs_by_expander = self.grouped_outputs_by_expander
            except ValueError:
                pass

        def configure_inputs() -> None:
            try:
                _inputs_screen = self.screen_order.index("inputs")
                input_groups = [
                    f"Inputs screen {i + 1}"
                    for i in range(0, len(self.host_data.inputs), 1)
                ]
                self.screen_order.pop(_inputs_screen)
                self.screen_order[_inputs_screen:_inputs_screen] = input_groups
                self.input_groups = input_groups
            except ValueError:
                _LOGGER.debug("No inputs configured. Omitting in screen.")

        try:
            _ina219_screen = self.screen_order.index("ina219")
            self.screen_order.pop(_ina219_screen)
        except ValueError:
            pass

        configure_outputs()
        configure_inputs()
        if not self.screen_order:
            raise ValueError("No available screens configured. OLED won't be working.")

        self._screen_order = cycle(self.screen_order)
        self._current_screen = next(self._screen_order)
        self.gpio_manager.init(pin=OLED_PIN, mode="in", pull_mode="gpio_pu")
        self.gpio_manager.add_event_callback(
            pin=OLED_PIN,
            callback=self._handle_press,
            debounce_period=timedelta(milliseconds=240),
            edge=Edge.FALLING,
        )
        try:
            serial = i2c(port=2, address=0x3C)
            self._device = sh1106(serial)
        except DeviceNotFoundError as err:
            raise I2CError(err)
        _LOGGER.debug("Configuring OLED screen.")
        self.tg.start_soon(self._sleeptime)

    def _draw_standard(self, data: dict, draw: ImageDraw.ImageDraw) -> None:
        """Draw standard information about host screen."""
        draw.text(
            (1, 1),
            self._current_screen.replace("_", " ").capitalize(),
            font=fonts["big"],
            fill="white",
        )
        row_no = START_ROW
        for k in data:
            draw.text(
                (3, row_no),
                f"{k} {data[k]}",
                font=fonts["small"],
                fill="white",
            )
            row_no += 15

    async def _sleeptime(self) -> None:
        if self.sleep_timeout.total_seconds() <= 0:
            return
        while True:
            delta = datetime.now(tz=timezone.utc) - self.press_time_at
            if delta >= self.sleep_timeout:
                with canvas(self._device) as draw:
                    draw.rectangle(
                        self._device.bounding_box, outline="black", fill="black"
                    )
                self.sleep = True
                _LOGGER.debug("OLED is going to sleep.")
                await self.sleep_event.wait()
            else:
                await anyio.sleep((self.sleep_timeout - delta).total_seconds())

    def _draw_uptime(self, data: dict, draw: ImageDraw.ImageDraw) -> None:
        """Draw uptime screen with boneIO logo."""
        draw.text((3, 3), "bone", font=fonts["danube"], fill="white")
        draw.text((53, 3), "iO", font=fonts["danube"], fill="white")
        for k in data:
            text = data[k]["data"]
            fontSize = fonts[data[k]["fontSize"]]
            draw.text(
                (data[k]["col"], UPTIME_ROWS[data[k]["row"]]),
                f"{k}: {text}",
                font=fontSize,
                fill="white",
            )

    def _draw_output(self, data: dict, draw: ImageDraw.ImageDraw) -> None:
        "Draw outputs of GPIO/MCP relays."
        cols = cycle(OUTPUT_COLS)
        draw.text(
            (1, 1),
            f"Relay {self._current_screen}",
            font=fonts["small"],
            fill="white",
        )
        i = 0
        j = next(cols)
        for k in data.values():
            if len(OUTPUT_ROWS) == i:
                j = next(cols)
                i = 0
            draw.text(
                (j, OUTPUT_ROWS[i]),
                f"{shorten_name(k['name'])} {k['state']}",
                font=fonts["extraSmall"],
                fill="white",
            )
            i += 1

    def _draw_input(self, data: dict, draw: ImageDraw.ImageDraw) -> None:
        "Draw inputs of boneIO Black."
        cols = cycle(INPUT_COLS)
        draw.text(
            (1, 1),
            f"{self._current_screen}",
            font=fonts["small"],
            fill="white",
        )
        i = 0
        j = next(cols)
        for k in data.values():
            if len(INPUT_ROWS) == i:
                j = next(cols)
                i = 0
            draw.text(
                (j, INPUT_ROWS[i]),
                f"{shorten_name(k['name'])} {k['state']}",
                font=fonts["extraSmall"],
                fill="white",
            )
            i += 1

    def render_display(self) -> None:
        """Render display."""
        if self._current_screen is None:
            return
        data = self.host_data.get(self._current_screen)
        if data is not None:
            if self._current_screen == "web":
                self.draw_qr_code(url=data)
            else:
                with canvas(self._device) as draw:
                    if self._current_screen in self.grouped_outputs_by_expander:
                        self._draw_output(data, draw)
                        for id in data.keys():
                            self.event_bus.add_event_listener(
                                event_type=EventType.OUTPUT,
                                entity_id=id,
                                listener_id=f"oled_{self._current_screen}",
                                target=self._output_callback,
                            )
                    elif self._current_screen == "uptime":
                        self._draw_uptime(data, draw)
                        self.event_bus.add_event_listener(
                            event_type=EventType.HOST,
                            entity_id=f"{self._current_screen}_hoststats",
                            listener_id=f"oled_{self._current_screen}",
                            target=self._standard_callback,
                        )
                    elif (
                        self.input_groups and self._current_screen in self.input_groups
                    ):
                        for id in data.keys():
                            self.event_bus.add_event_listener(
                                event_type=EventType.INPUT,
                                entity_id=id,
                                listener_id=f"oled_{self._current_screen}",
                                target=self._input_callback,
                            )
                        self._draw_input(data, draw)
                    else:
                        self._draw_standard(data, draw)
                        self.event_bus.add_event_listener(
                            event_type=EventType.HOST,
                            entity_id=f"{self._current_screen}_hoststats",
                            listener_id=f"oled_{self._current_screen}",
                            target=self._standard_callback,
                        )
        else:
            self._handle_press()

    async def _output_callback(self, event: OutputState) -> None:
        if self._current_screen in self.grouped_outputs_by_expander:
            self.handle_data_update(type=self._current_screen)

    async def _standard_callback(self, event: SensorState) -> None:
        self.handle_data_update(type="uptime")

    async def _input_callback(self, event: InputState) -> None:
        self.handle_data_update(type="inputs")

    def handle_data_update(self, type: str) -> None:
        """Callback to handle new data present into screen."""
        if not self._current_screen:
            return
        if (
            type == "inputs"
            and self._current_screen in self.input_groups
            or type == self._current_screen
        ) and not self.sleep:
            self.render_display()

    def _handle_press(self) -> None:
        """Handle press of PIN for OLED display."""
        _LOGGER.debug("Handling press OLED button!")
        self.press_time_at = datetime.now(tz=timezone.utc)
        self.sleep_event.set()

        if not self.sleep:
            self.event_bus.remove_event_listener(
                listener_id=f"oled_{self._current_screen}"
            )
            self._current_screen = next(self._screen_order)
        else:
            self.sleep = False
        self.render_display()
        self.sleep_event = anyio.Event()

    def draw_qr_code(self, url: str) -> None:
        """Draw QR code on the OLED display."""
        if not url:
            return

        # Create QR code with box_size 2 and scale down later
        qr = qrcode.QRCode(version=1, box_size=2, border=1)
        qr.add_data(url)
        qr.make(fit=True)

        # Create QR code image
        qr_image = qr.make_image(fill_color="white", back_color="black")
        qr_image = qr_image.convert("1")  # Convert to binary mode

        # Scale the QR code down to 0.8 of its size
        # Create a blank image with OLED dimensions
        display_image = Image.new(
            "1", (128, 64), 0
        )  # Mode 1, size 128x64, black background
        draw = ImageDraw.Draw(display_image)

        # Add title text on the left side
        # text_width = fonts["small"].getsize(title)[0]
        draw.text((2, 2), "Scan to", font=fonts["small"], fill="white")
        draw.text((2, 12), "access", font=fonts["small"], fill="white")
        draw.text((2, 22), "webui", font=fonts["small"], fill="white")

        # Calculate position to align QR code to right and center vertically
        x = 128 - qr_image.size[0] - 2  # Align to right with 2 pixels padding
        y = (64 - qr_image.size[1]) // 2  # Center vertically

        # Paste QR code onto center of display image
        display_image.paste(qr_image, (x, y))

        # Display the centered QR code
        self._device.display(display_image)
