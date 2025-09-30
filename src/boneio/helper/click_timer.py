from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

import anyio
import anyio.abc


@dataclass
class ClickTimer:
    """Represent async call later function with variable to check if timing is ON."""

    tg: anyio.abc.TaskGroup
    delay: float
    action: Callable[[float], None]
    event: anyio.Event = field(default_factory=anyio.Event)

    def is_waiting(self) -> bool:
        """If variable is set then timer is ON, if None is Off."""
        return self.event.is_set()

    def reset(self) -> None:
        """Uninitialize variable remove_listener."""
        if not self.event.is_set():
            self.event.set()

    async def start_timer(self) -> None:
        """Start timer."""
        self.event = anyio.Event()
        start_time = time.time()
        await anyio.sleep(self.delay)
        if not self.event.is_set():
            self.action(round(time.time() - start_time, 2))
            self.event.set()
