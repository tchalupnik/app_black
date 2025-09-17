from __future__ import annotations

import logging
import threading
import time
import typing
from collections.abc import Callable
from datetime import timedelta

from boneio.config import CoverConfig
from boneio.cover.cover import BaseCover
from boneio.helper.state_manager import CoverStateEntry
from boneio.models import CoverDirection, CoverStateOperation

if typing.TYPE_CHECKING:
    from boneio.helper.events import EventBus
    from boneio.message_bus.basic import MessageBus
    from boneio.relay import MCPRelay

_LOGGER = logging.getLogger(__name__)
COVER_MOVE_UPDATE_INTERVAL = 50  # ms
TILT_MOVE_UPDATE_INTERVAL = 10  # ms
DEFAULT_RESTORED_STATE = {"position": 100, "tilt": 100}


class VenetianCover(BaseCover):
    """Time-based cover algorithm similar to ESPHome, with tilt support.
    Uses a dedicated thread for precise timing control of cover movement."""

    def __init__(
        self,
        id: str,
        open_relay: MCPRelay,
        close_relay: MCPRelay,
        state_save: Callable[[CoverStateEntry], None],
        open_time: timedelta,
        close_time: timedelta,
        event_bus: EventBus,
        message_bus: MessageBus,
        topic_prefix: str,
        tilt_duration: timedelta,  # ms
        restored_state: CoverStateEntry,
    ) -> None:
        self._tilt_duration = (
            tilt_duration.total_seconds() * 1000
        )  # Czas trwania ruchu lameli
        self._initial_tilt_position = None

        position = int(restored_state.position)
        # --- TILT ---
        assert restored_state.tilt is not None, "Tilt cannot be None!"
        self.tilt = int(restored_state.tilt)

        self._last_tilt_update = 0.0

        super().__init__(
            id=id,
            open_relay=open_relay,
            close_relay=close_relay,
            state_save=state_save,
            open_time=open_time,
            close_time=close_time,
            event_bus=event_bus,
            message_bus=message_bus,
            topic_prefix=topic_prefix,
            position=position,
        )

    def _move_cover(
        self,
        direction: CoverDirection,
        duration: float,
        tilt_duration: float,
        target_position: int | None = None,
        target_tilt_position: int | None = None,
    ) -> None:
        """Moving cover in separate thread."""
        tilt_delta = (
            abs(self._initial_tilt_position - target_tilt_position)
            if target_tilt_position is not None
            else 0
        )
        if direction == CoverDirection.OPEN:
            relay = self._open_relay
            total_steps = 100 - self._position
            total_tilt_step = (
                tilt_delta
                if target_tilt_position is not None
                else 100 - self._initial_tilt_position
            )

        elif direction == CoverDirection.CLOSE:
            relay = self._close_relay
            total_steps = self._position
            total_tilt_step = (
                tilt_delta
                if target_tilt_position is not None
                else self._initial_tilt_position
            )
        else:
            raise ValueError(f"Wrong direction {direction}!")
        if target_tilt_position is not None:
            if tilt_delta < 1:
                total_steps = 0
            else:
                total_steps = 1

        if total_steps == 0 or duration == 0:
            self._current_operation = CoverStateOperation.IDLE
            self._loop.call_soon_threadsafe(self.send_state)
            return

        relay.turn_on()
        start_time = time.monotonic()
        progress = 0.0
        tilt_progress = 0.0
        needed_tilt_duration = tilt_duration * (total_tilt_step / 100)
        if target_tilt_position is None:
            tilt_delta = 1.0

        while not self._stop_event.is_set():
            current_time = (
                time.monotonic()
            )  # Pobierz aktualny czas tylko raz na iterację
            elapsed_time = (
                current_time - start_time
            ) * 1000  # Konwersja na milisekundy

            if elapsed_time < needed_tilt_duration:
                tilt_progress = elapsed_time / needed_tilt_duration
                progress = 0.0
            else:
                tilt_progress = 1.0
                progress = (elapsed_time - needed_tilt_duration) / duration

            if direction == CoverDirection.OPEN:
                # Obliczanie _position dla kierunku OPEN
                self._position = min(100.0, self._initial_position + progress * 100)

                # Obliczanie _tilt_position dla kierunku OPEN
                if target_tilt_position is not None:
                    self.tilt = min(
                        target_tilt_position,
                        self._initial_tilt_position + tilt_progress * tilt_delta,
                    )
                else:  # Fallback jeśli nie ma target_tilt_position
                    self.tilt = min(
                        100.0,
                        self._initial_tilt_position
                        + tilt_progress * (100 - self._initial_tilt_position),
                    )
            elif direction == CoverDirection.CLOSE:
                # Obliczanie _position dla kierunku CLOSE
                self._position = max(0.0, self._initial_position - progress * 100)

                # Obliczanie _tilt_position dla kierunku CLOSE
                if target_tilt_position is not None:
                    self.tilt = max(
                        target_tilt_position,
                        self._initial_tilt_position - tilt_progress * tilt_delta,
                    )
                else:  # Fallback jeśli nie ma target_tilt_position
                    self.tilt = max(
                        0.0,
                        self._initial_tilt_position
                        - tilt_progress * self._initial_tilt_position,
                    )

            self.timestamp = current_time  # Użyj pobranego czasu
            if current_time - self._last_update_time >= 1:
                self._loop.call_soon_threadsafe(self.send_state)
                self._last_update_time = current_time

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
                time.sleep(0.01)
            else:
                time.sleep(0.05)
        relay.turn_off()
        self._current_operation = CoverStateOperation.IDLE
        self._loop.call_soon_threadsafe(self.send_state_and_save)
        self._last_update_time = (
            time.monotonic()
        )  # Upewnij się, że aktualizacja jest wysłana na końcu ruchu

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

    def update_config_times(self, config: CoverConfig) -> None:
        self._actuator_activation_duration = (
            config.actuator_activation_duration or self._actuator_activation_duration
        )
        self._tilt_duration = config.tilt_duration or self._tilt_duration

    async def run_cover(
        self,
        current_operation: CoverStateOperation,
        target_position: int | None = None,
        target_tilt_position: int | None = None,
    ) -> None:
        if self._movement_thread and self._movement_thread.is_alive():
            _LOGGER.warning("Cover movement is already in progress. Stopping first.")
            await self.stop()

        self._current_operation = current_operation
        self._initial_position = self._position
        self._initial_tilt_position = self.tilt
        self._stop_event.clear()
        self._last_update_time = (
            time.monotonic()
        )  # Inicjalizacja czasu ostatniej aktualizacji

        if current_operation == CoverStateOperation.OPENING:
            self._movement_thread = threading.Thread(
                target=self._move_cover,
                args=(
                    CoverDirection.OPEN,
                    self._open_time,
                    self._tilt_duration,
                    target_position,
                    target_tilt_position,
                ),
            )
            self._movement_thread.start()
        elif current_operation == CoverStateOperation.CLOSING:
            self._movement_thread = threading.Thread(
                target=self._move_cover,
                args=(
                    CoverDirection.CLOSE,
                    self._close_time,
                    self._tilt_duration,
                    target_position,
                    target_tilt_position,
                ),
            )
            self._movement_thread.start()
