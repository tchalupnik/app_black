from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator, Callable, Iterable
from contextlib import ExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Literal

import anyio
import anyio.abc
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
    tg: anyio.abc.TaskGroup
    pins: dict[str, _Pin] = field(default_factory=dict)
    chips: dict[str, gpiod.Chip] = field(default_factory=dict, init=False)

    @classmethod
    @asynccontextmanager
    async def create(cls) -> AsyncGenerator[GpioManager]:
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
            async with anyio.create_task_group() as tg:
                yield cls(stack=stack, tg=tg, pins=pins)

    def init(
        self,
        pin: str,
        mode: Literal["in", "out"],
        pull_mode: Literal["gpio", "gpio_pu", "gpio_pd", "gpio_input"] = "gpio",
    ) -> None:
        """Set up a GPIO as input."""

        if mode == "in":
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
            direction = gpiod.line.Direction.INPUT
        elif mode == "out":
            if pull_mode is not None:
                raise ValueError(
                    "Configuration error: Mode `OUT` and `pull_mode` different than none!"
                )
            direction = gpiod.line.Direction.OUTPUT
        else:
            raise ValueError("Wrong gpio direction!")

        gpio_pin = self.pins[pin]
        config: dict[Iterable[int | str] | int | str, gpiod.LineSettings | None] = {
            gpio_pin.offset: gpiod.LineSettings(direction=direction, bias=bias)
        }
        chip = self.chips.get(gpio_pin.chip_path)

        def configure(chip: gpiod.Chip) -> None:
            if gpio_pin.configured is None or gpio_pin.request_line is None:
                gpio_pin.request_line = chip.request_lines(config=config)
                gpio_pin.configured = mode
            else:
                gpio_pin.request_line.reconfigure_lines(config=config)

        if chip is None:
            with gpiod.Chip(gpio_pin.chip_path) as chip:
                configure(chip)
        else:
            configure(chip)

    def write(self, pin: str, value: Literal["high", "low"]) -> None:
        """Write a value to a GPIO."""
        _LOGGER.debug("[%s] write to pin, value %s", pin, value)
        gpio_pin = self.pins[pin]
        if gpio_pin.configured is None or gpio_pin.request_line is None:
            raise ValueError(f"Pin {pin} is not configured!")
        if gpio_pin.configured == "in":
            gpio_pin.request_line.reconfigure_lines(
                config={
                    gpio_pin.offset: gpiod.LineSettings(
                        direction=gpiod.line.Direction.OUTPUT
                    )
                }
            )
            gpio_pin.configured = "out"
        gpio_pin.request_line.set_value(
            gpio_pin.offset,
            gpiod.line.Value.ACTIVE if value == "high" else gpiod.line.Value.INACTIVE,
        )

    def read(self, pin: str) -> bool:
        """Read a value from a GPIO."""
        _LOGGER.debug("[%s] read from pin", pin)
        gpio_pin = self.pins[pin]

        if gpio_pin.configured is None or gpio_pin.request_line is None:
            raise ValueError(f"Pin {pin} is not configured!")
        if gpio_pin.configured == "out":
            gpio_pin.request_line.reconfigure_lines(
                config={
                    gpio_pin.offset: gpiod.LineSettings(
                        direction=gpiod.line.Direction.INPUT
                    )
                }
            )
            gpio_pin.configured = "in"
        return gpio_pin.request_line.get_values()[0] == gpiod.line.Value.ACTIVE

    def add_event_callback(
        self,
        pin: str,
        callback: Callable[[], None],
        edge: Edge = Edge.BOTH,
        debounce_period: timedelta = timedelta(milliseconds=100),
    ) -> None:
        _LOGGER.debug("add_event_callback, pin: %s", pin)
        gpio_pin = self.pins[pin]

        if gpio_pin.configured is None or gpio_pin.request_line is None:
            raise ValueError(f"Pin {pin} is not configured!")

        gpio_pin.request_line.reconfigure_lines(
            config={
                gpio_pin.offset: gpiod.LineSettings(
                    direction=gpiod.line.Direction.INPUT,
                    edge_detection=gpiod.line.Edge.BOTH,
                    # debounce_period=debounce_period,
                )
            }
        )

        self.tg.start_soon(
            self._add_event_callback,
            pin,
            gpio_pin.request_line,
            edge,
            callback,
            debounce_period,
        )

    async def _add_event_callback(
        self,
        pin: str,
        request: gpiod.LineRequest,
        edge: Edge,
        callback: Callable[[], None],
        debounce_period: timedelta,
    ) -> None:
        """Add detection for RISING and FALLING events."""
        sender, receiver = anyio.create_memory_object_stream[
            list[gpiod.edge_event.EdgeEvent]
        ]()

        async def c() -> None:
            while True:
                await anyio.wait_readable(request.fd)
                events = request.read_edge_events()
                if not len(events):
                    return

                if edge == Edge.FALLING:
                    events = [
                        event
                        for event in events
                        if event.event_type
                        == gpiod.edge_event.EdgeEvent.Type.FALLING_EDGE
                    ]

                elif edge == Edge.RISING:
                    events = [
                        event
                        for event in events
                        if event.event_type
                        == gpiod.edge_event.EdgeEvent.Type.RISING_EDGE
                    ]

                _LOGGER.debug(
                    "Processing %s event(s) for pin %s on edge %s.",
                    len(events),
                    pin,
                    edge,
                )
                await sender.send(events)

        self.tg.start_soon(c)

        async with receiver:
            while True:
                result = await receiver.receive()
                # debounce_period is bugged
                await anyio.sleep(debounce_period.total_seconds())
                for _ in result:
                    _LOGGER.debug("add_event_callback calling callback on pin: %s", pin)
                    callback()
