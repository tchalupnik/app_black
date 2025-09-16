from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import ExitStack, contextmanager
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
    stack: ExitStack
    chips: dict[str, gpiod.Chip] = field(default_factory=dict, init=False)
    pins: dict[str, _Pin] = field(default_factory=dict, init=False)
    _loop: asyncio.AbstractEventLoop = field(
        default_factory=asyncio.get_event_loop, init=False
    )

    @classmethod
    @contextmanager
    def create(cls) -> Generator[GpioManager]:
        pins: dict[str, _Pin] = {}
        for entry in os.scandir("/dev/"):
            if not gpiod.is_gpiochip_device(entry.path):
                continue

            with gpiod.Chip(entry.path) as chip:
                for line in range(chip.get_info().num_lines):
                    line_info = chip.get_line_info(line)
                    line_name = line_info.name.split(" ")[0]
                    pins[line_name] = _Pin(chip_path=entry.path, offset=line)
        with ExitStack() as stack:
            yield cls(stack=stack, pins=pins)

    def setup_input(self, pin: str, pull_mode: str = "gpio") -> None:
        """Set up a GPIO as input."""
        gpio_mode = {
            "gpio": gpiod.line.Bias.DISABLED,
            "gpio_pu": gpiod.line.Bias.PULL_UP,
            "gpio_pd": gpiod.line.Bias.PULL_DOWN,
            "gpio_input": gpiod.line.Bias.DISABLED,
        }.get(pull_mode)

        line = self.pins[pin]
        chip = self.chips.get(line.chip_path)
        if chip is not None:
            chip = self.stack.enter_context(gpiod.Chip(line.chip_path))

        chip.request_lines(
            config={
                line.offset: gpiod.LineSettings(
                    direction=gpiod.line.Direction.INPUT, bias=gpio_mode
                )
            },
        )

    def write(self, pin: str, value: HIGH | LOW) -> None:
        """Write a value to a GPIO."""
        line = self.pins[pin]
        chip = self.chips.get(line.chip_path)
        if chip is not None:
            chip = self.stack.enter_context(gpiod.Chip(line.chip_path))

        request = chip.request_lines(
            config={
                line.offset: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT)
            },
        )
        request.set_value(
            line.offset,
            gpiod.line.Value.ACTIVE if value == HIGH else gpiod.line.Value.INACTIVE,
        )

    def read(self, pin: str) -> bool:
        """Read a value from a GPIO."""
        line = self.pins[pin]
        chip = self.chips.get(line.chip_path)
        if chip is not None:
            chip = self.stack.enter_context(gpiod.Chip(line.chip_path))

        request = chip.request_lines(
            config={
                line.offset: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT)
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

        chip = self.chips.get(line.chip_path)
        if chip is not None:
            chip = self.stack.enter_context(gpiod.Chip(line.chip_path))
            self.chips[line.chip_path] = chip

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
            if not len(events):
                return
            self.last_value_from_callback[pin] = (
                events[-1].event_type == gpiod.edge_event.EdgeEvent.Type.RISING_EDGE
            )
            if fut.done():
                return

            if edge == FALLING:
                events = [
                    event
                    for event in events
                    if event.event_type == gpiod.edge_event.EdgeEvent.Type.FALLING_EDGE
                ]

            elif edge == RISING:
                events = [
                    event
                    for event in events
                    if event.event_type == gpiod.edge_event.EdgeEvent.Type.RISING_EDGE
                ]

            _LOGGER.debug(
                "Processing %s event(s) for pin %s on edge %s.",
                len(events),
                pin,
                edge,
            )
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
