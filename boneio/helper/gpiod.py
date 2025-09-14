from __future__ import annotations

import os
import asyncio
from collections.abc import Callable
from datetime import timedelta

from typing_extensions import Literal
import gpiod

from boneio.const import BOTH, FALLING, GPIO, HIGH, LOW, RISING

class _Pin:
    def __init__(self, chip_path: str, offset: int) -> None:
        self.chip_path = chip_path
        self.offset = offset


class GpioManager:
    def __init__(self):
        self.pins: dict[str, _Pin] = {}
        self._loop = asyncio.get_event_loop()

        for entry in os.scandir("/dev/"):
            if not gpiod.is_gpiochip_device(entry.path):
                continue

            with gpiod.Chip(entry.path) as chip:
                for line in range(chip.get_info().num_lines):
                    line_info = chip.get_line_info(line)
                    line_name = line_info.name.split(" ")[0]
                    self.pins[line_name] = _Pin(chip_path=entry.path, offset=line)

    def setup_input(self, pin: str, pull_mode: str = GPIO) -> None:
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

    def write(self, pin: str, value: Literal[LOW, HIGH]) -> None:
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
        edge: Literal[FALLING, RISING, BOTH] = BOTH,
        debounce_period: timedelta = timedelta(milliseconds=100),
    ) -> None:
        """Add detection for RISING, FALLING and BOTH events."""
        asyncio.create_task(
            self._add_event_callback(
                pin=pin, edge=edge, callback=callback, debounce_period=debounce_period
            )
        )

    async def _add_event_callback(
        self,
        pin: str,
        edge: Literal[FALLING, RISING, BOTH],
        callback: Callable[[], None],
        debounce_period: timedelta,
    ) -> None:
        gpiod_edge = {
            FALLING: gpiod.line.Edge.FALLING,
            RISING: gpiod.line.Edge.RISING,
            BOTH: gpiod.line.Edge.BOTH,
        }[edge]

        line = self.pins[pin]
        with gpiod.Chip(line.chip_path) as chip:
            request = chip.request_lines(
                config={
                    line.offset: gpiod.LineSettings(
                        edge_detection=gpiod_edge,
                        # Unfortunately, gpiod's debounce is broken
                        # debounce_period=debounce_period,
                    )
                },
            )

            fut = self._loop.create_future()

            def on_change():
                events = request.read_edge_events()
                fut.set_result(events)

            self._loop.add_reader(request.fd, on_change)

            while True:
                await fut
                events = fut.result()
                # debounce_period is bugged when it becomes fixed remove line below.
                await asyncio.sleep(debounce_period.total_seconds())
                fut = self._loop.create_future()
                for _ in events:
                    callback()
