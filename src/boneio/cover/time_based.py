from __future__ import annotations

import logging
import threading
import time
import typing
from collections.abc import Callable
from datetime import timedelta

from boneio.config import CoverConfig
from boneio.cover.cover import BaseCover
from boneio.helper.events import EventBus
from boneio.helper.state_manager import CoverStateEntry
from boneio.models import CoverDirection, CoverStateOperation
from boneio.relay import MCPRelay

if typing.TYPE_CHECKING:
    from boneio.message_bus.basic import MessageBus

_LOGGER = logging.getLogger(__name__)


class TimeBasedCover(BaseCover):
    """Time-based cover algorithm similar to ESPHome."""

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
        restored_state: CoverStateEntry,
    ) -> None:
        position = int(restored_state.position)
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
        target_position: int | None = None,
    ):
        """Metoda uruchamiana w oddzielnym wątku do fizycznego ruchu rolety."""
        if direction == CoverDirection.OPEN:
            relay = self._open_relay
            total_steps = 100 - self._position
        elif direction == CoverDirection.CLOSE:
            relay = self._close_relay
            total_steps = self._position
        else:
            return

        if total_steps == 0 or duration == 0:
            self._current_operation = CoverStateOperation.IDLE
            self._loop.call_soon_threadsafe(self.send_state)
            return

        relay.turn_on()
        start_time = time.monotonic()

        while not self._stop_event.is_set():
            current_time = (
                time.monotonic()
            )  # Pobierz aktualny czas tylko raz na iterację
            elapsed_time = (
                current_time - start_time
            ) * 1000  # Konwersja na milisekundy
            progress = elapsed_time / duration

            if direction == CoverDirection.OPEN:
                self._position = min(100.0, self._initial_position + progress * 100)
            elif direction == CoverDirection.CLOSE:
                self._position = max(0.0, self._initial_position - progress * 100)

            self.timestamp = current_time  # Użyj pobranego czasu
            if current_time - self._last_update_time >= 1:
                self._loop.call_soon_threadsafe(self.send_state)
                self._last_update_time = current_time

            if target_position is not None:
                if (
                    direction == CoverDirection.OPEN
                    and self._position >= target_position
                ) or (
                    direction == CoverDirection.CLOSE
                    and self._position <= target_position
                ):
                    break

            if progress >= 1.0:
                break

            time.sleep(0.05)  # Małe opóźnienie, aby nie blokować CPU
        relay.turn_off()
        self._current_operation = CoverStateOperation.IDLE
        self._loop.call_soon_threadsafe(self.send_state_and_save)
        self._last_update_time = (
            time.monotonic()
        )  # Upewnij się, że aktualizacja jest wysłana na końcu ruchu

    async def run_cover(
        self,
        current_operation: CoverStateOperation,
        target_position: int | None = None,
        target_tilt: float | None = None,
    ) -> None:
        if (
            self._movement_thread
            and self._movement_thread.is_alive()
            or current_operation == CoverStateOperation.STOP
        ):
            _LOGGER.warning("Ruch rolety już trwa. Najpierw zatrzymaj.")
            await self.stop()

        self._current_operation = current_operation
        self._initial_position = self._position
        self._stop_event.clear()
        self._last_update_time = (
            time.monotonic() - 1
        )  # Inicjalizacja czasu ostatniej aktualizacji

        if current_operation == CoverStateOperation.OPENING:
            self._movement_thread = threading.Thread(
                target=self._move_cover,
                args=(CoverDirection.OPEN, self._open_time, target_position),
            )
            self._movement_thread.start()
        elif current_operation == CoverStateOperation.CLOSING:
            self._movement_thread = threading.Thread(
                target=self._move_cover,
                args=(CoverDirection.CLOSE, self._close_time, target_position),
            )
            self._movement_thread.start()

    def update_config_times(self, config: CoverConfig) -> None:
        pass
