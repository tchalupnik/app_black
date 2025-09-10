from __future__ import annotations

import asyncio
import time
from datetime import timedelta

# Typing imports that create a circular dependency
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..manager import Manager


class AsyncUpdater:
    def __init__(
        self, manager: Manager, update_interval: timedelta = timedelta(seconds=60)
    ) -> None:
        self.manager = manager
        self._update_interval = update_interval
        self.manager.append_task(coro=self._refresh(), name=self.id)
        self._timestamp = time.time()

    async def _refresh(self) -> None:
        try:
            while True:
                if hasattr(self, "async_update"):
                    update_interval = (
                        await self.async_update(timestamp=time.time())
                        or self._update_interval.total_seconds()
                    )
                else:
                    update_interval = (
                        self.update(timestamp=time.time())
                        or self._update_interval.total_seconds()
                    )
                await asyncio.sleep(update_interval)
        except asyncio.CancelledError:
            raise

    @property
    def last_timestamp(self) -> float:
        return self._timestamp
