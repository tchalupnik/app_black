from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta

import anyio
from anyio import Event

from boneio.config import VenetianCoverConfig
from boneio.cover.cover import BaseCover
from boneio.models import CoverDirection, CoverStateOperation

_LOGGER = logging.getLogger(__name__)


@dataclass(kw_only=True)
class VenetianCover(BaseCover):
    """Time-based cover algorithm similar to ESPHome, with tilt support.
    Uses a dedicated thread for precise timing control of cover movement."""

    tilt_delta: timedelta
    initial_tilt_position: int = field(init=False)
    # TODO: requires attention, probably doesnt do anything
    actuator_activation_duration: timedelta

    def __post_init__(self) -> None:
        super().__post_init__()
        self.initial_tilt_position = self.tilt

    async def _move_cover(
        self,
        direction: CoverDirection,
        target_position: int | None = None,
        target_tilt_position: int | None = None,
    ) -> None:
        """Moving cover in separate thread."""
        tilt_duration = self.tilt_delta.total_seconds() * 1000
        tilt_delta = (
            abs(self.initial_tilt_position - target_tilt_position)
            if target_tilt_position is not None
            else 0
        )
        if direction == CoverDirection.OPEN:
            relay = self.open_relay
            total_steps = 100 - self.position
            total_tilt_step = (
                tilt_delta
                if target_tilt_position is not None
                else 100 - self.initial_tilt_position
            )

        elif direction == CoverDirection.CLOSE:
            relay = self.close_relay
            total_steps = self.position
            total_tilt_step = (
                tilt_delta
                if target_tilt_position is not None
                else self.initial_tilt_position
            )
        else:
            raise ValueError(f"Wrong direction {direction}!")
        if target_tilt_position is not None:
            if tilt_delta < 1:
                total_steps = 0
            else:
                total_steps = 1

        if total_steps == 0 or tilt_duration == 0:
            self.current_operation = CoverStateOperation.IDLE
            self.send_state()
            return

        await relay.turn_on()
        start_time = time.monotonic()
        progress = 0
        tilt_progress = 0
        needed_tilt_duration = tilt_duration * (total_tilt_step / 100)
        if target_tilt_position is None:
            tilt_delta = 1

        while not self.stop_event.is_set():
            current_time = time.monotonic()
            elapsed_time = (current_time - start_time) * 1000

            if elapsed_time < needed_tilt_duration:
                tilt_progress = int(elapsed_time / needed_tilt_duration)
                progress = 0
            else:
                tilt_progress = 1
                progress = int((elapsed_time - needed_tilt_duration) / tilt_duration)

            if direction == CoverDirection.OPEN:
                self.position = min(100, self.initial_position + progress * 100)

                if target_tilt_position is not None:
                    self.tilt = min(
                        target_tilt_position,
                        self.initial_tilt_position + tilt_progress * tilt_delta,
                    )
                else:
                    self.tilt = min(
                        100,
                        self.initial_tilt_position
                        + tilt_progress * (100 - self.initial_tilt_position),
                    )
            elif direction == CoverDirection.CLOSE:
                self._position = max(0, self.initial_position - progress * 100)

                if target_tilt_position is not None:
                    self.tilt = max(
                        target_tilt_position,
                        self.initial_tilt_position - tilt_progress * tilt_delta,
                    )
                else:
                    self.tilt = max(
                        0,
                        self.initial_tilt_position
                        - tilt_progress * self.initial_tilt_position,
                    )

            self.timestamp = current_time
            if current_time - self.timestamp >= 1:
                self.send_state()
                self.timestamp = current_time

            if target_tilt_position is not None:
                if (
                    direction == CoverDirection.OPEN
                    and self.tilt >= target_tilt_position
                ) or (
                    direction == CoverDirection.CLOSE
                    and self.tilt <= target_tilt_position
                ):
                    break

            if target_position is not None:
                if (
                    direction == CoverDirection.OPEN
                    and self._position >= target_position
                ) or (
                    direction == CoverDirection.CLOSE
                    and self._position <= target_position
                ):
                    break

            if progress >= 1.0 or (target_tilt_position and tilt_progress >= 1.0):
                break

            if (
                target_tilt_position is not None
                and abs(self.tilt - target_tilt_position) < 5
            ):
                await anyio.sleep(0.01)
            else:
                await anyio.sleep(0.05)
        await relay.turn_off()
        self.current_operation = CoverStateOperation.IDLE
        self.send_state_and_save()
        self.timestamp = time.monotonic()

    async def set_tilt(self, tilt_position: int) -> None:
        """Setting tilt position."""
        if not 0 <= tilt_position <= 100:
            raise ValueError("Tilt position must be in range from 0 to 100.")

        if abs(self.tilt - tilt_position) < 1:
            return

        if tilt_position > self.tilt:
            await self.run_cover(
                current_operation=CoverStateOperation.OPENING,
                target_tilt_position=tilt_position,
            )
        elif tilt_position < self.tilt:
            await self.run_cover(
                current_operation=CoverStateOperation.CLOSING,
                target_tilt_position=tilt_position,
            )

    async def tilt_open(self) -> None:
        """Opening only tilt cover."""
        _LOGGER.info("Opening tilt cover %s", self.id)
        await self.set_tilt(tilt_position=100)

    async def tilt_close(self) -> None:
        """Closing only tilt cover."""
        _LOGGER.info("Closing tilt cover %s", self.id)
        await self.set_tilt(tilt_position=0)

    def update_config_times(self, config: VenetianCoverConfig) -> None:
        self.actuator_activation_duration = config.actuator_activation_duration
        self.tilt_delta = config.tilt_duration

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

        self.current_operation = current_operation
        self.initial_position = self.position
        self.initial_tilt_position = self.tilt
        self.stop_event = Event()
        self.timestamp = time.monotonic()

        if current_operation == CoverStateOperation.OPENING:
            await self._move_cover(
                CoverDirection.OPEN,
                target_position,
                target_tilt_position,
            )
        elif current_operation == CoverStateOperation.CLOSING:
            await self._move_cover(
                CoverDirection.CLOSE,
                target_position,
                target_tilt_position,
            )
