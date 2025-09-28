from __future__ import annotations

import asyncio
import signal
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import anyio
from click import ClickException
from hypercorn.utils import LifespanFailureError


class CommandInterrupted(ClickException):
    """When command line is interrupted."""


async def handle_signals(msg: str) -> None:
    if threading.main_thread() != threading.current_thread():
        # not running in main thread. Happens in gui.
        # Don't need signal handlers in gui; it handles signals itself
        return

    with anyio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signals:
        async for signum in signals:
            signame = signal.Signals(signum).name
            raise CommandInterrupted(f"{msg} ({signame}). Exiting...")


_T = TypeVar("_T")


def asyncio_run(
    handler: Callable[..., Coroutine[Any, Any, _T]], **kwargs: object
) -> _T:
    async def fun() -> _T:
        def asyncio_loop_exception_handler(
            loop: asyncio.AbstractEventLoop, context: dict[str, Any]
        ) -> None:
            exception = context.get("exception")
            if isinstance(exception, LifespanFailureError):
                pass
            else:
                loop.default_exception_handler(context)

        asyncio.get_event_loop().set_exception_handler(asyncio_loop_exception_handler)

        try:
            return await handler(**kwargs)
        except* CommandInterrupted:
            pass

    return asyncio.run(fun())
