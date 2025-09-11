from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

import gpiod  # type: ignore

BOTH = Literal["BOTH"]
FALLING = Literal["FALLING"]
RISING = Literal["RISING"]
HIGH = Literal["HIGH"]
LOW = Literal["LOW"]


@dataclass
class _Line:
    name: str
    chip: gpiod.Chip
    offset: int


@dataclass
class GpioManager:
    lines: dict[str, _Line]
    _loop: asyncio.AbstractEventLoop = field(default_factory=asyncio.get_event_loop)
    _line_requests: dict[str, gpiod.LineRequest] = field(default_factory=dict)

    @classmethod
    @contextmanager
    def create(cls) -> Generator[GpioManager]:
        chips: list[gpiod.Chip] = []
        lines: dict[str, _Line] = {}

        for entry in os.scandir("/dev/"):
            if not gpiod.is_gpiochip_device(entry.path):
                continue

            chip = gpiod.Chip(entry.path)
            chips.append(chip)
            for line in range(chip.get_info().num_lines):
                line_info = chip.get_line_info(line)
                line_name = line_info.name.split(" ")[0]
                lines[line_name] = _Line(name=line_name, chip=chip, offset=line)

        try:
            this = cls(lines=lines)
            yield this
        finally:
            for chip in chips:
                chip.close()

    def _setup_output(self, pin: str, initial: HIGH | LOW = LOW) -> None:
        line = self.lines[pin]
        request = line.chip.request_lines(
            config={
                line.offset: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT)
            },
        )
        request.set_value(
            line.offset,
            gpiod.line.Value.ACTIVE if initial == HIGH else gpiod.line.Value.INACTIVE,
        )
        self._line_requests[pin] = request

    def setup_input(self, pin: str, pull_mode: str = "gpio") -> None:
        """Set up a GPIO as input."""
        gpio_mode = {
            "gpio": gpiod.line.Bias.DISABLED,
            "gpio_pu": gpiod.line.Bias.PULL_UP,
            "gpio_pd": gpiod.line.Bias.PULL_DOWN,
            "gpio_input": gpiod.line.Bias.DISABLED,
        }.get(pull_mode)

        line = self.lines[pin]
        request = line.chip.request_lines(
            config={
                line.offset: gpiod.LineSettings(
                    direction=gpiod.line.Direction.INPUT, bias=gpio_mode
                )
            },
        )
        self._line_requests[pin] = request

    def write(self, pin: str, value: HIGH | LOW) -> None:
        """Write a value to a GPIO."""
        if pin in self._line_requests:
            request = self._line_requests[pin]
            request.set_value(
                pin,
                gpiod.line.Value.ACTIVE if value == HIGH else gpiod.line.Value.INACTIVE,
            )
            return
        self._setup_output(pin, value)

    def read(self, pin: str) -> bool:
        """Read a value from a GPIO."""
        if pin not in self._line_requests:
            raise ValueError(f"Pin '{pin}' not set up.")
        request = self._line_requests[pin]
        value = request.get_values()[0]
        return value == gpiod.line.Value.ACTIVE

    def add_event_callback(
        self,
        pin: str,
        callback: Callable[[], None],
        edge: FALLING | RISING | BOTH = BOTH,
        debounce_period: timedelta = timedelta(milliseconds=100),
    ) -> None:
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

        gpiod_edge = {
            FALLING: gpiod.line.Edge.FALLING,
            RISING: gpiod.line.Edge.RISING,
            BOTH: gpiod.line.Edge.BOTH,
        }[edge]

        request = self._line_requests.get(pin)
        if request is None:
            line = self.lines[pin]
            request = line.chip.request_lines(
                config={
                    line.offset: gpiod.LineSettings(
                        edge_detection=gpiod_edge,
                        debounce_period=debounce_period,
                    )
                },
            )

        fut = self._loop.create_future()

        def c():
            events = request.read_edge_events()
            fut.set_result(events)

        self._loop.add_reader(request.fd, c)

        while True:
            await fut
            events = fut.result()
            fut = self._loop.create_future()
            for _ in events:
                callback()
