from __future__ import annotations

import logging
import socket
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import cycle
from math import floor
from pathlib import Path
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

import anyio.abc
import psutil
import qrcode
from luma.core.error import DeviceNotFoundError
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106
from PIL import Image, ImageDraw, ImageFont
from qrcode.image.pure import PyPNGImage

from boneio.config import Config, OledScreens
from boneio.events import Event, EventBus, EventType, HostEvent
from boneio.gpio_manager import Edge, GpioManagerBase
from boneio.helper import I2CError
from boneio.helper.async_updater import refresh_wrapper
from boneio.helper.util import batched
from boneio.message_bus.basic import MessageBus
from boneio.modbus.coordinator import ModbusCoordinator
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

FONTS = {
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


class Screen(Protocol):
    def _draw(self, draw: ImageDraw.ImageDraw) -> None:
        """Render display."""

    async def render(self) -> None:
        """Context manager to handle event listener registration and removal."""


@dataclass
class Oled:
    """Oled display class."""

    tg: anyio.abc.TaskGroup
    config: Config
    event_bus: EventBus
    message_bus: MessageBus
    gpio_manager: GpioManagerBase
    outputs: dict[str, BasicRelay]
    inputs: dict[str, GpioEventButtonsAndSensors]
    temp_sensors: list[TempSensor]
    ina219: INA219 | None
    modbus_coordinators: dict[str, ModbusCoordinator]
    screen_order: list[OledScreens] = field(init=False)
    sleep_timeout: timedelta = field(init=False)
    sleep_event: anyio.Event = field(default_factory=anyio.Event, init=False)
    press_event: anyio.Event = field(default_factory=anyio.Event, init=False)
    input_groups: list[str] = field(default_factory=list, init=False)
    press_time_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc), init=False
    )
    screens: list[Screen] = field(init=False, default_factory=list)
    cycling_screens: cycle[Screen] = field(init=False)
    _device: sh1106 = field(init=False)

    def __post_init__(self) -> None:
        """Initialize OLED screen."""
        assert self.config.oled is not None

        self.screen_order = self.config.oled.screens.copy()
        if not self.screen_order:
            raise ValueError("No available screens configured. OLED won't be working.")

        try:
            serial = i2c(port=2, address=0x3C)
            self._device = sh1106(serial)
        except DeviceNotFoundError as err:
            raise I2CError(err)
        _LOGGER.debug("Configuring OLED screen.")

        self.sleep_timeout = self.config.oled.screensaver_timeout

        def get_temperature() -> float | None:
            if not self.temp_sensors:
                return None
            return self.temp_sensors[0].state

        def web_url() -> str:
            if self.config.web is None:
                return "No IP"
            network_state = get_network_info()
            if "ip" in network_state:
                return f"http://{network_state['ip']}:{self.config.web.port}"
            return "No IP"

        def update_default_screen(
            func: Callable[[], dict[str, str]],
        ) -> Callable[[DefaultScreen], None]:
            def wrapped(screen: DefaultScreen) -> None:
                screen.data = func()

            return wrapped

        def update_uptime_screen(screen: UptimeScreen) -> None:
            screen.temperature = get_temperature()
            screen.is_connection_established = (
                self.message_bus.is_connection_established()
            )

        all_screens: dict[str, Screen] = {
            "network": UpdatingScreen[DefaultScreen](
                screen=DefaultScreen(
                    name="network", device=self._device, data=get_network_info()
                ),
                event_bus=self.event_bus,
                callback=update_default_screen(get_network_info),
            ),
            "cpu": UpdatingScreen[DefaultScreen](
                screen=DefaultScreen(
                    name="cpu", device=self._device, data=get_cpu_info()
                ),
                event_bus=self.event_bus,
                update_interval=timedelta(seconds=5),
                callback=update_default_screen(get_cpu_info),
            ),
            "disk": UpdatingScreen[DefaultScreen](
                screen=DefaultScreen(
                    name="disk", device=self._device, data=get_disk_info()
                ),
                event_bus=self.event_bus,
                callback=update_default_screen(get_disk_info),
            ),
            "memory": UpdatingScreen[DefaultScreen](
                screen=DefaultScreen(
                    name="memory", device=self._device, data=get_memory_info()
                ),
                event_bus=self.event_bus,
                callback=update_default_screen(get_memory_info),
            ),
            "swap": UpdatingScreen(
                screen=DefaultScreen(
                    name="swap", device=self._device, data=get_swap_info()
                ),
                event_bus=self.event_bus,
                callback=update_default_screen(get_swap_info),
            ),
            "uptime": UpdatingScreen(
                screen=UptimeScreen(
                    name="uptime",
                    device=self._device,
                    is_connection_established=self.message_bus.is_connection_established(),
                    temperature=get_temperature(),
                ),
                event_bus=self.event_bus,
                update_interval=timedelta(seconds=30),
                callback=update_uptime_screen,
            ),
            "web": WebScreen(
                name="web",
                device=self._device,
                url=web_url(),
            ),
        }
        if self.ina219 is not None:

            def update_ina219_screen() -> dict[str, str]:
                if self.ina219 is None:
                    return {}
                return {
                    str(
                        sensor.device_class
                    ): f"{sensor.state} {sensor.unit_of_measurement}"
                    for sensor in self.ina219.sensors.values()
                }

            all_screens["ina219"] = UpdatingScreen(
                screen=DefaultScreen(
                    name="ina219",
                    device=self._device,
                    data={
                        str(
                            sensor.device_class
                        ): f"{sensor.state} {sensor.unit_of_measurement}"
                        for sensor in self.ina219.sensors.values()
                    },
                ),
                event_bus=self.event_bus,
                callback=update_default_screen(update_ina219_screen),
            )

        for extra_screen in self.config.oled.extra_screen_sensors:
            if extra_screen.sensor_type == "modbus":
                if extra_screen.modbus_id is None:
                    _LOGGER.warning(
                        "Modbus ID not set for extra screen sensor %s",
                        extra_screen.sensor_id,
                    )
                    continue
                _modbus_coordinator = self.modbus_coordinators.get(
                    extra_screen.modbus_id
                )
                if _modbus_coordinator is None:
                    _LOGGER.warning(
                        "Modbus ID %s not found for extra screen sensor %s",
                        extra_screen.modbus_id,
                        extra_screen.sensor_id,
                    )
                    continue
                entity = _modbus_coordinator.get_entity_by_name(extra_screen.sensor_id)
                if entity is None:
                    _LOGGER.warning(
                        "Sensor %s not found for extra screen sensor %s",
                        extra_screen.sensor_id,
                        extra_screen.sensor_id,
                    )
                    continue
                value = (
                    round(entity.state, 2)
                    if isinstance(entity.state, float)
                    else entity.state
                )
                all_screens[extra_screen.sensor_id] = UpdatingScreen(
                    screen=DefaultScreen(
                        name=extra_screen.sensor_id,
                        device=self._device,
                        data={
                            "".join(
                                [x[:3] for x in entity.name.split()]
                            ): f"{value} {entity.unit_of_measurement}"
                        },
                    ),
                    event_bus=self.event_bus,
                    callback=update_default_screen(
                        lambda: {
                            "".join(
                                [x[:3] for x in entity.name.split()]
                            ): f"{value} {entity.unit_of_measurement}"
                        }
                    ),
                )
            elif extra_screen.sensor_type == "dallas":
                sensor = next(
                    (
                        s
                        for s in self.temp_sensors
                        if s.id.lower() == extra_screen.sensor_id.lower()
                    ),
                    None,
                )
                if sensor is None:
                    _LOGGER.warning(
                        "Dallas sensor %s not found for extra screen sensor",
                        extra_screen.sensor_id,
                    )
                    continue
                all_screens[extra_screen.sensor_id] = UpdatingScreen(
                    screen=DefaultScreen(
                        name=extra_screen.sensor_id,
                        device=self._device,
                        data={sensor.name: f"{round(sensor.state, 2)} C"},
                    ),
                    event_bus=self.event_bus,
                    callback=update_default_screen(
                        lambda: {sensor.name: f"{round(sensor.state, 2)} C"}
                    ),
                )
            else:
                raise ValueError(
                    f"Sensor type {extra_screen.sensor_type} not supported"
                )

        for screen_entry in self.screen_order:
            screen = all_screens.get(screen_entry)
            if screen is None:
                _LOGGER.warning("Screen %s not found, omitting.", screen_entry)
                continue
            if isinstance(screen, OutputScreen):
                if self.outputs:

                    def update_output_screen(screen: OutputScreen) -> None:
                        screen.outputs = tuple(self.outputs.values())

                    outputs_batched = batched(self.outputs.values(), 24)
                    for i, outputs_chunk in enumerate(outputs_batched):
                        self.screens.append(
                            UpdatingScreen(
                                screen=OutputScreen(
                                    name=f"outputs_{i + 1}",
                                    outputs=outputs_chunk,
                                    device=self._device,
                                ),
                                event_bus=self.event_bus,
                                callback=update_output_screen,
                            )
                        )
                else:
                    _LOGGER.debug("No outputs configured. Omitting in screen.")
                    continue
            if isinstance(screen, InputScreen):
                if self.inputs:

                    def update_input_screen(screen: InputScreen) -> None:
                        screen.inputs = tuple(self.inputs.values())

                    inputs_batched = batched(self.inputs.values(), 24)
                    for i, inputs_chunk in enumerate(inputs_batched):
                        self.screens.append(
                            UpdatingScreen(
                                screen=InputScreen(
                                    name=f"inputs_{i + 1}",
                                    inputs=inputs_chunk,
                                    device=self._device,
                                ),
                                event_bus=self.event_bus,
                                callback=update_input_screen,
                            )
                        )
                else:
                    _LOGGER.debug("No inputs configured. Omitting in screen.")
                    continue
            else:
                self.screens.append(screen)

        self.cycling_screens = cycle(self.screens)

        self.gpio_manager.init(pin=OLED_PIN, mode="in", pull_mode="gpio_pu")
        self.gpio_manager.add_event_callback(
            pin=OLED_PIN,
            callback=self._handle_press,
            debounce_period=timedelta(milliseconds=240),
            edge=Edge.FALLING,
        )
        if self.sleep_timeout.total_seconds() > 0:
            _LOGGER.debug(
                "OLED screensaver timeout set to %s seconds.",
                self.sleep_timeout.total_seconds(),
            )
            self.tg.start_soon(self._sleeptime)
        for screen in self.screens:
            if isinstance(screen, UpdatingScreen):
                self.tg.start_soon(
                    refresh_wrapper(
                        screen.trigger,
                        screen.update_interval,
                    )
                )

    async def _sleeptime(self) -> None:
        while True:
            delta = datetime.now(tz=timezone.utc) - self.press_time_at
            if delta >= self.sleep_timeout:
                with canvas(self._device) as draw:
                    draw.rectangle(
                        self._device.bounding_box, outline="black", fill="black"
                    )
                _LOGGER.debug("OLED is going to sleep.")
                await self.sleep_event.wait()
            else:
                await anyio.sleep((self.sleep_timeout - delta).total_seconds())

    async def render_display(self) -> None:
        """Render display."""
        while True:
            self.press_event = anyio.Event()
            screen = next(self.cycling_screens)
            async with anyio.create_task_group() as tg:
                tg.start_soon(screen.render)
                await self.press_event.wait()
                tg.cancel_scope.cancel()

    def _handle_press(self) -> None:
        """Handle press of PIN for OLED display."""
        _LOGGER.debug("Handling press OLED button!")
        self.press_time_at = datetime.now(tz=timezone.utc)
        self.press_event.set()
        self.sleep_event.set()
        self.sleep_event = anyio.Event()


@dataclass(kw_only=True)
class ScreenBase(ABC):
    name: str
    device: sh1106

    @abstractmethod
    def _draw(self, draw: ImageDraw.ImageDraw) -> None:
        """Render display."""

    async def render(self) -> None:
        with canvas(self.device) as draw:
            self._draw(draw=draw)
        await anyio.sleep_forever()


_T = TypeVar("_T", bound=ScreenBase)


@dataclass
class UpdatingScreen(Generic[_T]):
    screen: _T
    event_bus: EventBus
    callback: Callable[[_T], None]
    event_type: EventType = EventType.HOST
    update_interval: timedelta = field(default=timedelta(seconds=60))
    callback_triggered_event: anyio.Event = field(
        default_factory=anyio.Event, init=False
    )

    def _draw(self, draw: ImageDraw.ImageDraw) -> None:
        """Draw screen."""
        self.screen._draw(draw=draw)

    @property
    def name(self) -> str:
        return self.screen.name

    async def _trigger_callback_and_event(self, event: Event) -> None:
        self.callback(self.screen)
        self.callback_triggered_event.set()

    async def render(self) -> None:
        """Context manager to handle event listener registration and removal."""
        if self.update_interval is not None:
            self.event_bus.add_event_listener(
                event_type=self.event_type,
                entity_id=f"{self.name}_screen",
                listener_id=f"oled_{self.screen.name}",
                target=self._trigger_callback_and_event,
            )
        try:
            while True:
                async with anyio.create_task_group() as tg:
                    tg.start_soon(self.screen.render)
                    await self.callback_triggered_event.wait()
                    self.callback_triggered_event = anyio.Event()
                    tg.cancel_scope.cancel()

        finally:
            if self.update_interval is not None:
                self.event_bus.remove_event_listener(listener_id=f"oled_{self.name}")

    def trigger(self, timestamp: float) -> None:
        """Update screen."""
        match self.event_type:
            case EventType.HOST:
                event = HostEvent(
                    event_type=EventType.HOST,
                    event_state=None,
                    entity_id=f"{self.name}_screen",
                )
        self.event_bus.trigger_event(event=event)


@dataclass(kw_only=True)
class UptimeScreen(ScreenBase):
    is_connection_established: bool
    temperature: float | None = None

    def _draw(self, draw: ImageDraw.ImageDraw) -> None:
        """Draw uptime screen with boneIO logo."""
        draw.text((3, 3), "bone", font=FONTS["danube"], fill="white")
        draw.text((53, 3), "iO", font=FONTS["danube"], fill="white")
        draw.text(
            (3, UPTIME_ROWS[0]),
            "host: " + socket.gethostname(),
            font=FONTS["small"],
            fill="white",
        )
        draw.text(
            (3, UPTIME_ROWS[1]),
            f"ver: {__version__}",
            font=FONTS["small"],
            fill="white",
        )
        draw.text(
            (3, UPTIME_ROWS[2]),
            f"uptime: {get_uptime()}",
            font=FONTS["small"],
            fill="white",
        )
        draw.text(
            (60, UPTIME_ROWS[3]),
            "MQTT: CONN" if self.is_connection_established else "MQTT: DOWN",
            font=FONTS["small"],
            fill="white",
        )
        if self.temperature is not None:
            draw.text(
                (3, UPTIME_ROWS[3]),
                f"T: {self.temperature} C",
                font=FONTS["small"],
                fill="white",
            )


@dataclass(kw_only=True)
class DefaultScreen(ScreenBase):
    data: dict[str, str]

    def _draw(self, draw: ImageDraw.ImageDraw) -> None:
        """Draw standard information about host screen."""
        draw.text(
            (1, 1),
            self.name.replace("_", " ").capitalize(),
            font=FONTS["big"],
            fill="white",
        )
        row_no = START_ROW
        for entry in self.data:
            draw.text(
                (3, row_no),
                f"{entry} {self.data[entry]}",
                font=FONTS["small"],
                fill="white",
            )
            row_no += 15


@dataclass(kw_only=True)
class WebScreen(ScreenBase):
    url: str

    def _draw(self, draw: ImageDraw.ImageDraw) -> None:
        """Draw QR code on the OLED display."""
        # Create QR code with box_size 2 and scale down later
        qr = qrcode.QRCode(version=1, box_size=2, border=1)
        qr.add_data(self.url)
        qr.make(fit=True)

        # Create QR code image
        qr_image = qr.make_image(fill_color="white", back_color="black")
        if isinstance(qr_image, PyPNGImage):
            raise ValueError("PNG image not supported for OLED display.")
        qr_image = qr_image.convert("1")  # Convert to binary mode

        # Scale the QR code down to 0.8 of its size
        # Create a blank image with OLED dimensions
        display_image = Image.new(
            "1", (128, 64), 0
        )  # Mode 1, size 128x64, black background
        draw = ImageDraw.Draw(display_image)

        # Add title text on the left side
        # text_width = fonts["small"].getsize(title)[0]
        draw.text((2, 2), "Scan to", font=FONTS["small"], fill="white")
        draw.text((2, 12), "access", font=FONTS["small"], fill="white")
        draw.text((2, 22), "webui", font=FONTS["small"], fill="white")

        # Calculate position to align QR code to right and center vertically
        x = 128 - qr_image.size[0] - 2  # Align to right with 2 pixels padding
        y = (64 - qr_image.size[1]) // 2  # Center vertically

        # Paste QR code onto center of display image
        display_image.paste(qr_image, (x, y))

        # Display the centered QR code
        self.device.display(display_image)


@dataclass(kw_only=True)
class InputScreen(ScreenBase):
    inputs: tuple[GpioEventButtonsAndSensors, ...]

    def _draw(self, draw: ImageDraw.ImageDraw) -> None:
        "Draw inputs of boneIO Black."
        cols = cycle(INPUT_COLS)
        draw.text(
            (1, 1),
            f"{self.name}",
            font=FONTS["small"],
            fill="white",
        )
        i = 0
        j = next(cols)
        for input in self.inputs:
            if len(INPUT_ROWS) == i:
                j = next(cols)
                i = 0
            draw.text(
                (j, INPUT_ROWS[i]),
                f"{shorten_name(input.name)} {input.state}",
                font=FONTS["extraSmall"],
                fill="white",
            )
            i += 1


@dataclass(kw_only=True)
class OutputScreen(ScreenBase):
    outputs: tuple[BasicRelay, ...]

    def _draw(self, draw: ImageDraw.ImageDraw) -> None:
        "Draw outputs of GPIO/MCP relays."
        cols = cycle(OUTPUT_COLS)
        draw.text(
            (1, 1),
            f"Relay {self.name}",
            font=FONTS["small"],
            fill="white",
        )
        i = 0
        j = next(cols)
        for output in self.outputs:
            if len(OUTPUT_ROWS) == i:
                j = next(cols)
                i = 0
            draw.text(
                (j, OUTPUT_ROWS[i]),
                f"{shorten_name(output.name or output.id)} {output.state}",
                font=FONTS["extraSmall"],
                fill="white",
            )
            i += 1
