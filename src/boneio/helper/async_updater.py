from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from datetime import timedelta

import anyio


def refresh_wrapper(
    func: Callable[[float], Coroutine[None, None, None]],
    update_interval: timedelta = timedelta(seconds=60),
) -> Callable[[], Coroutine[None, None, None]]:
    """Wrap a function to be called periodically."""
    timestamp = time.time()

    async def wrapped():
        while True:
            if asyncio.iscoroutinefunction(func):
                await func(timestamp)
            else:
                func(timestamp)
            await anyio.sleep(update_interval.total_seconds())

    return wrapped
