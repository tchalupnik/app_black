from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Literal

import gpiod

_LOGGER = logging.getLogger(__name__)


class Edge(Enum):
    BOTH = "BOTH"
    FALLING = "FALLING"
    RISING = "RISING"


@dataclass
class _Pin:
    chip_path: str
    offset: int
    configured: Literal["in", "out"] | None = None
    request_line: gpiod.line_request.LineRequest | None = None


@dataclass
class GpioManager:
    stack: ExitStack
    pins: dict[str, _Pin] = field(default_factory=dict)
    chips: dict[str, gpiod.Chip] = field(default_factory=dict, init=False)
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

    def init(
        self,
        pin: str,
        mode: Literal["in", "out"],
        pull_mode: Literal["gpio", "gpio_pu", "gpio_pd", "gpio_input"] | None = None,
    ) -> None:
        """Set up a GPIO as input."""

        if mode == "in":
            direction = gpiod.line.Direction.INPUT
        elif mode == "out":
            if pull_mode is not None:
                raise ValueError(
                    "Configuration error: Mode `OUT` and `pull_mode` different than none!"
                )
            direction = gpiod.line.Direction.OUTPUT
        else:
            raise ValueError("Wrong gpio direction!")

        if pull_mode == "gpio":
            bias = gpiod.line.Bias.DISABLED
        elif pull_mode == "gpio_pu":
            bias = gpiod.line.Bias.PULL_DOWN
        elif pull_mode == "gpio_pd":
            bias = gpiod.line.Bias.PULL_UP
        elif pull_mode == "gpio_input":
            bias = gpiod.line.Bias.DISABLED
        else:
            raise ValueError("Wrong gpio pull mode!")

        line = self.pins[pin]
        config = {line.offset: gpiod.LineSettings(direction=direction, bias=bias)}
        chip = self.chips.get(line.chip_path)

        def configure(chip: gpiod.Chip) -> None:
            if line.configured is None:
                line.request_line = chip.request_lines(config=config)
                line.configured = mode

            elif line.configured != mode:
                line.request_line.reconfigure_lines(config=config)

        if chip is None:
            with gpiod.Chip(line.chip_path) as chip:
                configure(chip)
        else:
            configure(chip)

    def write(self, pin: str, value: Literal["high", "low"]) -> None:
        """Write a value to a GPIO."""
        line = self.pins[pin]
        config = {
            line.offset: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT)
        }

        def _write(chip: gpiod.Chip) -> None:
            if line.configured == "in":
                line.request_line.reconfigure_lines(config=config)
            elif line.configured is None:
                line.request_line = chip.request_lines(config=config)
                line.configured = "out"
            line.request_line.set_value(
                line.offset,
                gpiod.line.Value.ACTIVE
                if value == "high"
                else gpiod.line.Value.INACTIVE,
            )

        chip = self.chips.get(line.chip_path)
        if chip is None:
            with gpiod.Chip(line.chip_path) as chip:
                _write(chip)
        else:
            _write(chip)

    def read(self, pin: str) -> bool:
        """Read a value from a GPIO."""
        line = self.pins[pin]
        config = {line.offset: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT)}

        def _read(
            chip: gpiod.Chip,
        ) -> gpiod.line.Value.ACTIVE | gpiod.line.Value.INACTIVE:
            if line.configured == "out":
                request = chip.reconfigure_lines(config=config)
            elif line.configured is None:
                request = chip.request_lines(config=config)
            return request.get_values()[0]

        chip = self.chips.get(line.chip_path)
        if chip is None:
            with gpiod.Chip(line.chip_path) as chip:
                value = _read(chip)
        else:
            value = _read(chip)

        return value == gpiod.line.Value.ACTIVE

    def add_event_callback(
        self,
        pin: str,
        callback: Callable[[], None],
        edge: Edge = Edge.BOTH,
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
        edge: Edge,
        callback: Callable[[], None],
        debounce_period: timedelta,
    ) -> AsyncGenerator[gpiod.LineEvent, None]:
        """Add detection for RISING and FALLING events."""
        line = self.pins[pin]

        chip = self.chips.get(line.chip_path)
        if chip is None:
            chip = self.stack.enter_context(gpiod.Chip(line.chip_path))
            self.chips[line.chip_path] = chip
        if line.configured is None:
            request = chip.request_lines(
                config={
                    line.offset: gpiod.LineSettings(
                        edge_detection=gpiod.line.Edge.BOTH,
                        # debounce_period=debounce_period,
                    )
                },
            )

        fut = self._loop.create_future()

        def c() -> None:
            events = request.read_edge_events()
            if not len(events):
                return
            if fut.done():
                return

            if edge == Edge.FALLING:
                events = [
                    event
                    for event in events
                    if event.event_type == gpiod.edge_event.EdgeEvent.Type.FALLING_EDGE
                ]

            elif edge == Edge.RISING:
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
