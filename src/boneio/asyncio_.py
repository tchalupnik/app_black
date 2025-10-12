from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import anyio
from click import ClickException
from hypercorn.utils import LifespanFailureError


class CommandInterrupted(ClickException):
    """When command line is interrupted."""


async def handle_signals(msg: str) -> None:
    with anyio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signals:
        async for signum in signals:
            signame = signal.Signals(signum).name
            raise CommandInterrupted(f"{msg} ({signame}). Exiting...")


_T = TypeVar("_T")


def asyncio_run(
    handler: Callable[..., Coroutine[Any, Any, _T]],
    *,
    backend_options: dict[str, Any] | None = None,
    **kwargs: object,
) -> None:
    async def fun() -> None:
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
            await handler(**kwargs)
        except* CommandInterrupted:
            pass

    return anyio.run(fun, backend_options=backend_options)
