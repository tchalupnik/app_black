from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import timedelta

import anyio


def refresh_wrapper(
    func: Callable[[], Coroutine[None, None, None]],
    update_interval: timedelta = timedelta(seconds=60),
) -> Callable[[], Coroutine[None, None, None]]:
    async def wrapped():
        while True:
            if asyncio.iscoroutinefunction(func):
                await func()
            else:
                func()
            await anyio.sleep(update_interval.total_seconds())

    return wrapped
