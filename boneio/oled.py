import asyncio
import logging
from itertools import cycle
from typing import List

from luma.core.error import DeviceNotFoundError
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106
from PIL import ImageDraw

from boneio.const import OLED_PIN, UPTIME, WHITE
from boneio.helper import (
    HostData,
    I2CError,
    TimePeriod,
    edge_detect,
    make_font,
    setup_input,
)
from boneio.helper.events import async_track_point_in_time, utcnow

_LOGGER = logging.getLogger(__name__)

fonts = {
    "big": make_font("DejaVuSans.ttf", 12),
    "small": make_font("DejaVuSans.ttf", 9),
    "extraSmall": make_font("DejaVuSans.ttf", 7),
    "danube": make_font("danube__.ttf", 15, local=True),
}

# screen_order = [UPTIME, NETWORK, CPU, DISK, MEMORY, SWAP]

# STANDARD_ROWS = [17, 32, 47]
START_ROW = 17
UPTIME_ROWS = list(range(22, 60, 10))
OUTPUT_ROWS = list(range(14, 60, 6))
INPUT_ROWS = list(range(12, 60, 6))
OUTPUT_COLS = range(0, 113, 56)
INPUT_COLS = range(0, 113, 30)


def shorten_name(name: str) -> str:
    if len(name) > 6:
        return f"{name[:4]}{name[-2:]}"
    return name


class Oled:
    """Oled display class."""

    def __init__(
        self,
        host_data: HostData,
        grouped_outputs: List[str],
        sleep_timeout: TimePeriod,
        screen_order: List[str],
    ) -> None:
        """Initialize OLED screen."""
        self._loop = asyncio.get_running_loop()
        self._grouped_outputs = None
        self._input_groups = []
        self._host_data = host_data

        def configure_outputs() -> None:
            try:
                _ind_screen = screen_order.index("outputs")
                if not grouped_outputs:
                    _LOGGER.debug("No outputs configured. Omitting in screen.")
                    return
                screen_order.pop(_ind_screen)
                screen_order[_ind_screen:_ind_screen] = grouped_outputs
                self._grouped_outputs = grouped_outputs
            except ValueError:
                pass

        def configure_inputs() -> None:
            try:
                _inputs_screen = screen_order.index("inputs")
                input_groups = [
                    f"Inputs screen {i + 1}"
                    for i in range(
                        0, self._host_data.inputs_length, 1
                    )  # self._host_data.inputs_length
                ]
                screen_order.pop(_inputs_screen)
                screen_order[_inputs_screen:_inputs_screen] = input_groups
                self._input_groups = input_groups
            except ValueError:
                _LOGGER.debug("No inputs configured. Omitting in screen.")
                pass

        try:
            _ina219_screen = screen_order.index("ina219")
            screen_order.pop(_ina219_screen)
        except ValueError:
            pass

        configure_outputs()
        configure_inputs()
        if not screen_order:
            _LOGGER.warning("No available screens configured. OLED won't be working.")
            self._current_screen = None
            return
        self._screen_order = cycle(screen_order)
        self._current_screen = next(self._screen_order)
        self._host_data = host_data
        self._sleep = False
        self._sleep_handle = None
        self._sleep_timeout = sleep_timeout
        setup_input(pin=OLED_PIN, pull_mode="gpio_pu")
        edge_detect(pin=OLED_PIN, callback=self._handle_press, bounce=240)
        try:
            serial = i2c(port=2, address=0x3C)
            self._device = sh1106(serial)
        except DeviceNotFoundError as err:
            raise I2CError(err)
        _LOGGER.debug("Configuring OLED screen.")

    def _draw_standard(self, data: dict, draw: ImageDraw) -> None:
        """Draw standard information about host screen."""
        draw.text(
            (1, 1),
            self._current_screen.replace("_", " ").capitalize(),
            font=fonts["big"],
            fill=WHITE,
        )
        row_no = START_ROW
        for k in data:
            draw.text(
                (3, row_no),
                f"{k} {data[k]}",
                font=fonts["small"],
                fill=WHITE,
            )
            row_no += 15

    def _sleeptime(self):
        with canvas(self._device) as draw:
            draw.rectangle(
                self._device.bounding_box, outline="black", fill="black"
            )
        self._sleep = True

    def _draw_uptime(self, data: dict, draw: ImageDraw) -> None:
        """Draw uptime screen with boneIO logo."""
        draw.text((3, 3), "bone", font=fonts["danube"], fill=WHITE)
        draw.text((53, 3), "iO", font=fonts["danube"], fill=WHITE)
        for k in data:
            text = data[k]["data"]
            fontSize = fonts[data[k]["fontSize"]]
            draw.text(
                (data[k]["col"], UPTIME_ROWS[data[k]["row"]]),
                f"{k}: {text}",
                font=fontSize,
                fill=WHITE,
            )

    def _draw_output(self, data: dict, draw: ImageDraw) -> None:
        "Draw outputs of GPIO/MCP relays."
        cols = cycle(OUTPUT_COLS)
        draw.text(
            (1, 1),
            f"Relay {self._current_screen}",
            font=fonts["small"],
            fill=WHITE,
        )
        i = 0
        j = next(cols)
        for k in data:
            if len(OUTPUT_ROWS) == i:
                j = next(cols)
                i = 0
            draw.text(
                (j, OUTPUT_ROWS[i]),
                f"{shorten_name(k)} {data[k]}",
                font=fonts["extraSmall"],
                fill=WHITE,
            )
            i += 1

    def _draw_input(self, data: dict, draw: ImageDraw) -> None:
        "Draw inputs of boneIO Black."
        cols = cycle(INPUT_COLS)
        draw.text(
            (1, 1),
            f"{self._current_screen}",
            font=fonts["small"],
            fill=WHITE,
        )
        i = 0
        j = next(cols)
        for k in data:
            if len(INPUT_ROWS) == i:
                j = next(cols)
                i = 0
            draw.text(
                (j, INPUT_ROWS[i]),
                f"{shorten_name(k)} {data[k]}",
                font=fonts["extraSmall"],
                fill=WHITE,
            )
            i += 1

    def render_display(self) -> None:
        """Render display."""
        data = self._host_data.get(self._current_screen)
        if data:
            with canvas(self._device) as draw:
                if (
                    self._grouped_outputs
                    and self._current_screen in self._grouped_outputs
                ):
                    self._draw_output(data, draw)
                elif self._current_screen == UPTIME:
                    self._draw_uptime(data, draw)
                elif (
                    self._input_groups
                    and self._current_screen in self._input_groups
                ):
                    self._draw_input(data, draw)
                else:
                    self._draw_standard(data, draw)
        else:
            self._handle_press(pin=None)
        if not self._sleep_handle and self._sleep_timeout.total_seconds > 0:
            self._sleep_handle = async_track_point_in_time(
                loop=self._loop,
                action=lambda x: self._sleeptime(),
                point_in_time=utcnow() + self._sleep_timeout.as_timedelta,
            )

    def handle_data_update(self, type: str):
        """Callback to handle new data present into screen."""
        if not self._current_screen:
            return
        if (
            type == "inputs"
            and self._current_screen in self._input_groups
            or type == self._current_screen
        ) and not self._sleep:
            self.render_display()

    def _handle_press(self, pin: any) -> None:
        """Handle press of PIN for OLED display."""
        if self._sleep_handle:
            self._sleep_handle()
            self._sleep_handle = None
        if not self._sleep:
            self._current_screen = next(self._screen_order)
        else:
            self._sleep = False
        self.render_display()
