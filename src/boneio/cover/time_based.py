from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta

import anyio

from boneio.cover.cover import BaseCover
from boneio.models import CoverDirection, CoverStateOperation

_LOGGER = logging.getLogger(__name__)


@dataclass
class TimeBasedCover(BaseCover):
    """Time-based cover algorithm similar to ESPHome."""

    async def _move_cover(
        self,
        direction: CoverDirection,
        delta: timedelta,
        target_position: int | None = None,
    ) -> None:
        """Metoda uruchamiana w oddzielnym wątku do fizycznego ruchu rolety."""
        duration = delta.total_seconds() * 1000
        if direction == CoverDirection.OPEN:
            relay = self.open_relay
            total_steps = 100 - self.position
        elif direction == CoverDirection.CLOSE:
            relay = self.close_relay
            total_steps = self.position
        else:
            return

        if total_steps == 0 or duration == 0:
            self._current_operation = CoverStateOperation.IDLE
            self.send_state()
            return

        await relay.turn_on()
        start_time = time.monotonic()

        while not self.stop_event.is_set():
            current_time = time.monotonic()
            elapsed_time = (current_time - start_time) * 1000
            progress = int(elapsed_time / duration)

            if direction == CoverDirection.OPEN:
                self.position = min(100, self._initial_position + progress * 100)
            elif direction == CoverDirection.CLOSE:
                self.position = max(0, self._initial_position - progress * 100)

            self.timestamp = current_time
            if current_time - self.timestamp >= 1:
                self.send_state()
                self.timestamp = current_time

            if target_position is not None:
                if (
                    direction == CoverDirection.OPEN
                    and self.position >= target_position
                ) or (
                    direction == CoverDirection.CLOSE
                    and self.position <= target_position
                ):
                    break

            if progress >= 1.0:
                break

            await anyio.sleep(0.05)
        await relay.turn_off()
        self._current_operation = CoverStateOperation.IDLE
        self.send_state_and_save()
        self.timestamp = time.monotonic()

    async def run_cover(
        self,
        current_operation: CoverStateOperation,
        target_position: int | None = None,
        target_tilt_position: int | None = None,
    ) -> None:
        if (
            not self.stop_event.is_set()
            or current_operation == CoverStateOperation.STOP
        ):
            _LOGGER.warning("Cover movement is already in progress. Stopping first.")
            await self.stop()

        self._current_operation = current_operation
        self._initial_position = self.position
        self.stop_event = anyio.Event()
        self.timestamp = time.monotonic() - 1

        if current_operation == CoverStateOperation.OPENING:
            await self._move_cover(CoverDirection.OPEN, self.open_time, target_position)
        elif current_operation == CoverStateOperation.CLOSING:
            await self._move_cover(
                CoverDirection.CLOSE, self.close_time, target_position
            )
