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
IN = Literal["IN"]
LOW = Literal["LOW"]
OUT = Literal["OUT"]


@dataclass
class GpioManager:
    _loop: asyncio.AbstractEventLoop = field(default_factory=asyncio.get_event_loop)
    _chips: list[gpiod.Chip] = field(default_factory=list)
    _line_requests: dict[str, gpiod.LineRequest] = field(default_factory=dict)

    @classmethod
    @contextmanager
    def create(cls) -> Generator[GpioManager]:
        paths = [
            entry.path
            for entry in os.scandir("/dev/")
            if gpiod.is_gpiochip_device(entry.path)
        ]
        try:
            this = cls(_chips=[gpiod.Chip(path) for path in paths])
            yield this
        finally:
            for chip in this._chips:
                chip.close()

    def _setup_output(self, pin: str, initial: HIGH | LOW = LOW) -> None:
        chip, line_offset = self._get_chip_and_offset_by_pin(pin)
        request = chip.request_lines(
            config={line_offset: gpiod.LineSettings(direction=gpiod.Direction.OUTPUT)},
        )
        request.set_value(
            line_offset, gpiod.Value.ACTIVE if initial == HIGH else gpiod.Value.INACTIVE
        )
        self._line_requests[pin] = request

    def setup_input(self, pin: str, pull_mode: str = "gpio") -> None:
        """Set up a GPIO as input."""
        gpio_mode = {
            "gpio": gpiod.BIAS.DISABLED,
            "gpio_pu": gpiod.BIAS.PULL_UP,
            "gpio_pd": gpiod.BIAS.PULL_DOWN,
            "gpio_input": gpiod.BIAS.DISABLED,
        }.get(pull_mode)

        chip, line_offset = self._get_chip_and_offset_by_pin(pin)
        request = chip.request_lines(
            config={
                line_offset: gpiod.LineSettings(
                    direction=gpiod.Direction.INPUT, bias=gpio_mode
                )
            },
        )
        self._line_requests[pin] = request

    def write(self, pin: str, value: HIGH | LOW) -> None:
        """Write a value to a GPIO."""
        if pin in self._line_requests:
            request = self._line_requests[pin]
            request.set_value(
                pin, gpiod.Value.ACTIVE if value == HIGH else gpiod.Value.INACTIVE
            )
            return
        self._setup_output(pin, value)

    def read(self, pin: str) -> bool:
        """Read a value from a GPIO."""
        if pin not in self._line_requests:
            raise ValueError(f"Pin '{pin}' not set up.")
        request = self._line_requests[pin]
        value = request.get_values()[0]
        return value == gpiod.Value.ACTIVE

    def add_event_callback(
        self,
        pin: str,
        edge: FALLING | RISING | BOTH,
        callback: Callable[[], None],
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
        chip, line_offset = self._get_chip_and_offset_by_pin(pin)

        gpiod_edge = {
            FALLING: gpiod.EDGE_FALLING,
            RISING: gpiod.EDGE_RISING,
            BOTH: gpiod.EDGE_BOTH,
        }[edge]

        request = chip.request_lines(
            config={
                line_offset: gpiod.LineSettings(
                    edge_detection=gpiod_edge,
                    debounce_period=debounce_period,
                )
            },
        )

        fut = self.loop.create_future()

        def c():
            events = request.read_edge_events()
            fut.set_result(events)

        self.loop.add_reader(request.fd, c)

        while True:
            await fut
            events = fut.result()
            fut = self.loop.create_future()
            for _ in events:
                callback()

    def _get_chip_and_offset_by_pin(self, pin: str) -> tuple[gpiod.Chip, int]:
        for chip in self._chips:
            try:
                offset = chip.line_offset_from_id(pin)
                return chip, offset
            except OSError:
                # An OSError is raised if the name is not found.
                continue
        raise ValueError(f"Line '{pin}' not found.")
