from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

import gpiod  # type: ignore

BOTH = Literal["BOTH"]
FALLING = Literal["FALLING"]
RISING = Literal["RISING"]
HIGH = Literal["HIGH"]
LOW = Literal["LOW"]


_LOGGER = logging.getLogger(__name__)


@dataclass
class _Pin:
    chip_path: str
    offset: int


@dataclass
class GpioManager:
    pins: dict[str, _Pin] = field(default_factory=dict, init=False)
    _loop: asyncio.AbstractEventLoop = field(
        default_factory=asyncio.get_event_loop, init=False
    )
    last_value_from_callback: dict[str, bool] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        pins: dict[str, _Pin] = {}

        for entry in os.scandir("/dev/"):
            if not gpiod.is_gpiochip_device(entry.path):
                continue

            with gpiod.Chip(entry.path) as chip:
                for line in range(chip.get_info().num_lines):
                    line_info = chip.get_line_info(line)
                    line_name = line_info.name.split(" ")[0]
                    pins[line_name] = _Pin(chip_path=entry.path, offset=line)
        self.pins = pins

    def setup_input(self, pin: str, pull_mode: str = "gpio") -> None:
        """Set up a GPIO as input."""
        gpio_mode = {
            "gpio": gpiod.line.Bias.DISABLED,
            "gpio_pu": gpiod.line.Bias.PULL_UP,
            "gpio_pd": gpiod.line.Bias.PULL_DOWN,
            "gpio_input": gpiod.line.Bias.DISABLED,
        }.get(pull_mode)

        line = self.pins[pin]
        with gpiod.Chip(line.chip_path) as chip:
            chip.request_lines(
                config={
                    line.offset: gpiod.LineSettings(
                        direction=gpiod.line.Direction.INPUT, bias=gpio_mode
                    )
                },
            )

    def write(self, pin: str, value: HIGH | LOW) -> None:
        """Write a value to a GPIO."""
        pin_gpiod = self.pins[pin]
        with gpiod.Chip(pin_gpiod.chip_path) as chip:
            request = chip.request_lines(
                config={
                    pin_gpiod.offset: gpiod.LineSettings(
                        direction=gpiod.line.Direction.OUTPUT
                    )
                },
            )
            request.set_value(
                pin_gpiod.offset,
                gpiod.line.Value.ACTIVE if value == HIGH else gpiod.line.Value.INACTIVE,
            )

    def read(self, pin: str) -> bool:
        """Read a value from a GPIO."""
        value = self.last_value_from_callback.get(pin)
        if value is not None:
            return value

        gpiod_pin = self.pins[pin]
        with gpiod.Chip(gpiod_pin.chip_path) as chip:
            request = chip.request_lines(
                config={
                    gpiod_pin.offset: gpiod.LineSettings(
                        direction=gpiod.line.Direction.INPUT
                    )
                },
            )
            value = request.get_values()[0]
        return value == gpiod.line.Value.ACTIVE

    def add_event_callback(
        self,
        pin: str,
        callback: Callable[[], None],
        edge: FALLING | RISING | BOTH = BOTH,
        debounce_period: timedelta = timedelta(milliseconds=100),
    ) -> None:
        _LOGGER.debug("add_event_callback, pin: %s", pin)

        asyncio.create_task(
            self._add_event_callback(
                pin=pin, edge=edge, callback=callback, debounce_period=debounce_period
            )
        )

    async def _add_event_callback(
        self,
        pin: str,
        edge: FALLING | RISING | BOTH,
        callback: Callable[[], None],
        debounce_period: timedelta,
    ) -> AsyncGenerator[gpiod.LineEvent, None]:
        """Add detection for RISING and FALLING events."""
        line = self.pins[pin]
        with gpiod.Chip(line.chip_path) as chip:
            request = chip.request_lines(
                config={
                    line.offset: gpiod.LineSettings(
                        edge_detection=gpiod.line.Edge.BOTH,
                        # debounce_period=debounce_period,
                    )
                },
            )

            fut = self._loop.create_future()

            def c():
                events = request.read_edge_events()
                self.last_value_from_callback[pin] = (
                    events[-1].event_type == gpiod.edge_event.EdgeEvent.Type.RISING_EDGE
                )
                if fut.done():
                    return

                if edge == FALLING:
                    events = [
                        event
                        for event in events
                        if event.event_type
                        == gpiod.edge_event.EdgeEvent.Type.FALLING_EDGE
                    ]

                elif edge == RISING:
                    events = [
                        event
                        for event in events
                        if event.event_type
                        == gpiod.edge_event.EdgeEvent.Type.RISING_EDGE
                    ]

                _LOGGER.debug(str(events))
                fut.set_result(events)

            self._loop.add_reader(request.fd, c)

            while True:
                await fut
                result = fut.result()
                # debounce_period is bugged
                await asyncio.sleep(debounce_period.total_seconds())
                fut = self._loop.create_future()
                for _ in result:
                    _LOGGER.debug("add_event_callback calling callback on pin: %s", pin)
                    callback()
